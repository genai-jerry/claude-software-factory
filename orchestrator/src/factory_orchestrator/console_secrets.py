"""Agent credentials from the Factory Console's secret store.

The Console (software-factory-view) retains the agent secrets set through
its UI — ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, FACTORY_CROSS_REPO_TOKEN
— in its `orchestrator_secrets` table, sealed with CONSOLE_MASTER_KEY using
its envelope format (`v1.<iv b64>.<tag b64>.<ct b64>`, AES-256-GCM, 32-byte
base64 master key). The Actions engine reads the same values from GitHub
Actions secrets, which the Console writes through; Actions secrets cannot be
read back, so this store is the orchestrator's path to them.

Precedence is explicit: an environment variable always wins; the Console
store only fills what the deployment left unset. Values are re-read on a
TTL, so rotating a secret in the Console reaches the orchestrator without a
redeploy — mirroring how the Console's own worker re-reads its credential
store per job.
"""

from __future__ import annotations

import base64
import logging
import time

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("factory-orchestrator.console-secrets")

AGENT_SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "FACTORY_CROSS_REPO_TOKEN")


class SealedSecretError(ValueError):
    pass


def decrypt_sealed(sealed: str, master_key_b64: str) -> str:
    """Open one Console-sealed secret. Format-compatible with crypto.ts."""
    parts = sealed.split(".")
    if len(parts) != 4 or parts[0] != "v1" or not all(parts[1:]):
        raise SealedSecretError("malformed sealed secret")
    try:
        key = base64.b64decode(master_key_b64)
    except ValueError as exc:
        raise SealedSecretError("master key is not valid base64") from exc
    if len(key) != 32:
        raise SealedSecretError("CONSOLE_MASTER_KEY must be 32 bytes, base64-encoded")
    try:
        iv, tag, ct = (base64.b64decode(p) for p in parts[1:])
        # AESGCM wants ciphertext||tag; the Console stores them separately.
        return AESGCM(key).decrypt(iv, ct + tag, None).decode()
    except (ValueError, InvalidTag) as exc:
        raise SealedSecretError("sealed secret failed to decrypt (wrong key?)") from exc


def seal(plaintext: str, master_key_b64: str) -> str:
    """Produce a Console-compatible sealed secret (tests and tooling)."""
    import os
    key = base64.b64decode(master_key_b64)
    iv = os.urandom(12)
    blob = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    ct, tag = blob[:-16], blob[-16:]
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"v1.{b64(iv)}.{b64(tag)}.{b64(ct)}"


class ConsoleSecretStore:
    """Reads (and decrypts) the Console's retained agent secrets.

    `org` may name the Console org id; when omitted and the table holds
    secrets for exactly one org, that org is used — more than one org
    without an explicit choice is an error rather than a guess.
    """

    def __init__(self, database_url: str, master_key_b64: str,
                 org: str | None = None, ttl_seconds: float = 60.0):
        self.engine = sa.create_engine(database_url, future=True)
        self.master_key = master_key_b64
        self.org = org or None
        self.ttl = ttl_seconds
        self._cache: dict[str, str] | None = None
        self._cached_at = 0.0

    def invalidate(self) -> None:
        self._cache = None

    def agent_secrets(self) -> dict[str, str]:
        if self._cache is not None and time.monotonic() - self._cached_at < self.ttl:
            return self._cache
        with self.engine.connect() as cx:
            rows = cx.execute(sa.text(
                "SELECT org_id, name, encrypted_value FROM orchestrator_secrets"
            )).fetchall()
        by_org: dict[str, dict[str, str]] = {}
        for org_id, name, sealed in rows:
            if name in AGENT_SECRETS:
                by_org.setdefault(str(org_id), {})[name] = sealed
        if self.org is not None:
            chosen = by_org.get(self.org, {})
        elif len(by_org) > 1:
            raise SealedSecretError(
                f"orchestrator_secrets holds secrets for {len(by_org)} orgs - "
                "set CONSOLE_ORG to the org id this orchestrator serves")
        else:
            chosen = next(iter(by_org.values()), {})
        secrets = {name: decrypt_sealed(sealed, self.master_key)
                   for name, sealed in chosen.items()}
        self._cache = secrets
        self._cached_at = time.monotonic()
        return secrets


def apply_console_secrets(env: dict[str, str],
                          store: ConsoleSecretStore) -> tuple[dict[str, str], set[str]]:
    """Fill agent secrets the environment left unset from the Console store.

    Returns the merged env and the names that came from the Console (only
    those are eligible for later refresh — deployment-set values stay).
    """
    merged = dict(env)
    from_console: set[str] = set()
    secrets = store.agent_secrets()
    for name in AGENT_SECRETS:
        if not merged.get(name) and secrets.get(name):
            merged[name] = secrets[name]
            from_console.add(name)
    if from_console:
        log.info("agent secrets from the Console store: %s", ", ".join(sorted(from_console)))
    return merged, from_console


def refresh_console_secrets(cfg, store: ConsoleSecretStore, from_console: set[str]) -> None:
    """Pick up rotated Console secrets without a restart.

    Only fields the Console supplied at startup are refreshed; env-set
    values keep deployment precedence. Config is shared by reference with
    the runner and probe, so an in-place update reaches the next role run.
    """
    if not from_console:
        return
    from .config import Secret
    store.invalidate()
    try:
        secrets = store.agent_secrets()
    except Exception:  # noqa: BLE001 - a flaky console DB must not kill the sweep
        log.warning("could not refresh Console secrets - keeping current values", exc_info=True)
        return
    field_of = {"ANTHROPIC_API_KEY": "anthropic_api_key",
                "CLAUDE_CODE_OAUTH_TOKEN": "claude_code_oauth_token",
                "FACTORY_CROSS_REPO_TOKEN": "cross_repo_token"}
    for name in from_console:
        value = secrets.get(name, "")
        if value and getattr(cfg, field_of[name]).reveal() != value:
            setattr(cfg, field_of[name], Secret(value))
            log.info("refreshed %s from the Console store", name)
