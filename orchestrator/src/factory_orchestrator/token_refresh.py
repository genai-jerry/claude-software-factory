"""Re-minting installation tokens through the Console.

The orchestrator authenticates to GitHub with an installation token that
lives about an hour. That is shorter than the work: ``ROLE_TIMEOUT_SECONDS``
alone is 45 minutes, roles fan out several at a time behind
``max_parallel`` slots, and every run ends with a guard read
(``verify_no_op`` -> ``GET /issues/{n}``) *after* the agent has stopped. A
token minted at dispatch is therefore routinely dead by the time the
run finishes, which surfaces as a bare ``401 Unauthorized`` on the run
record and takes the whole role's work with it.

An orchestrator holding a real App private key re-mints for itself. The
lighthouse-style deployment does not: it runs with the placeholder
``GITHUB_APP_ID=000000`` (see :func:`webhook.public_delivery_error`) and
receives its tokens from the Console on ``/dispatch``. For that deployment
the Console exposes ``POST /api/orchestrator/github-token``, which mints a
fresh token for an installation id. This module is the client for it —
the orchestrator half of a refresh path whose Console half already exists.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("factory-orchestrator.token")

REFRESH_PATH = "/api/orchestrator/github-token"


class TokenRefreshError(RuntimeError):
    """No usable installation token could be obtained."""


class ConsoleTokenSource:
    """Mints installation tokens by asking the Console that dispatched the run.

    ``console_url`` and ``installation_id`` both arrive on the dispatch
    payload, so a repo becomes refreshable the first time the Console asks
    the orchestrator to do anything with it.
    """

    def __init__(self, dispatch_token: str, *, client: httpx.Client | None = None,
                 timeout: float = 15.0):
        self.dispatch_token = dispatch_token
        self.timeout = timeout
        self._client = client
        self._installations: dict[str, tuple[str, int]] = {}

    def register(self, owner: str, repo: str, console_url: str | None,
                 installation_id: int | None) -> None:
        """Remember where a repo's tokens can be re-minted. Partial info is dropped."""
        if not console_url or not installation_id:
            return
        key = f"{owner}/{repo}"
        entry = (console_url.rstrip("/"), int(installation_id))
        if self._installations.get(key) != entry:
            log.info("token refresh available for %s via %s installation=%s",
                     key, entry[0], entry[1])
        self._installations[key] = entry

    def can_refresh(self, owner: str, repo: str) -> bool:
        return bool(self.dispatch_token) and f"{owner}/{repo}" in self._installations

    def console_origin(self, owner: str, repo: str) -> str | None:
        """The Console origin that dispatched this repo, if one has registered."""
        entry = self._installations.get(f"{owner}/{repo}")
        return entry[0] if entry else None

    def mint(self, owner: str, repo: str) -> tuple[str, str | None]:
        """Return ``(token, expires_at_iso)``. Raises :class:`TokenRefreshError`."""
        key = f"{owner}/{repo}"
        entry = self._installations.get(key)
        if not entry:
            raise TokenRefreshError(
                f"no Console endpoint is known for {key} — the dispatch that started "
                "this run did not carry console_url and installation_id")
        if not self.dispatch_token:
            raise TokenRefreshError(
                "DISPATCH_TOKEN is empty, so the orchestrator cannot authenticate to "
                "the Console to re-mint a GitHub token")
        base, installation_id = entry
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            r = client.post(
                f"{base}{REFRESH_PATH}",
                headers={"Authorization": f"Bearer {self.dispatch_token}"},
                json={"installation_id": installation_id},
            )
        except httpx.HTTPError as e:
            raise TokenRefreshError(f"could not reach the Console at {base}: {e}") from e
        finally:
            if self._client is None:
                client.close()
        if r.status_code >= 400:
            detail = ""
            try:
                detail = str((r.json() or {}).get("error") or "")
            except ValueError:
                detail = (r.text or "")[:200]
            raise TokenRefreshError(
                f"Console {base}{REFRESH_PATH} returned {r.status_code}"
                f"{': ' + detail if detail else ''}")
        data = r.json()
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise TokenRefreshError(f"Console {base}{REFRESH_PATH} returned no token")
        expires_at = data.get("expires_at")
        log.info("re-minted an installation token for %s (expires %s)",
                 key, expires_at or "unknown")
        return token, expires_at if isinstance(expires_at, str) else None
