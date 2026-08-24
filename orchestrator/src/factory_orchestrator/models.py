"""Model resolution: the repo's preference chains, probed for access.

Mirrors the Actions engine's "Resolve model" step: `.github/factory-models.json`
maps each role to a list of models in preference order; the first one the
credential can actually reach wins, each fallback is recorded as a warning,
a missing role falls back to the documented default, and an exhausted chain
fails the run with a clear error.

The probe is injectable. The default probe uses langchain-anthropic (a
one-token ping) when an API key is configured, and falls back to the claude
CLI for OAuth-token credentials, which the Anthropic SDK cannot use.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import Config, agent_path
from .github_app import RepoPort, parse_json_or_empty

log = logging.getLogger("factory-orchestrator.models")

DEFAULT_CHAIN = ["claude-sonnet-5"]
MODELS_PATH = ".github/factory-models.json"

Probe = Callable[[str], bool]


class ModelResolutionError(RuntimeError):
    pass


@dataclass
class ResolvedModel:
    model: str
    fallbacks: list[str] = field(default_factory=list)  # models probed and skipped


def chain_for(role: str, models_config: dict[str, Any]) -> list[str]:
    v = models_config.get(role, DEFAULT_CHAIN)
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
        return v
    return DEFAULT_CHAIN


def resolve_model(role: str, models_config: dict[str, Any], probe: Probe) -> ResolvedModel:
    chain = chain_for(role, models_config)
    skipped: list[str] = []
    for model in chain:
        log.info("Probing model access: %s", model)
        if probe(model):
            if skipped:
                log.warning("Model fallback for %s: %s inaccessible, using %s",
                            role, ", ".join(skipped), model)
            return ResolvedModel(model=model, fallbacks=skipped)
        log.warning("Model %s is not accessible with this credential - trying next in chain", model)
        skipped.append(model)
    raise ModelResolutionError(
        f"No model in the preference chain for '{role}' is accessible "
        f"({', '.join(chain)}) - check credentials/plan or edit {MODELS_PATH}")


def load_models_config(port: RepoPort, ref: str | None = None) -> dict[str, Any]:
    return parse_json_or_empty(port.get_file(MODELS_PATH, ref=ref))


def default_probe(cfg: Config) -> Probe:
    """One-token ping per model, cached for the process lifetime.

    Always uses the Claude CLI — the same binary the role run uses — so
    factory aliases like ``claude-opus-5`` resolve the way Claude Code
    does, not through the Anthropic Messages API (different ids).
    """
    cache: dict[str, bool] = {}

    def probe(model: str) -> bool:
        if model in cache:
            return cache[model]
        creds = cfg.agent_credential_env()
        if not creds:
            return False
        try:
            r = subprocess.run(
                ["claude", "-p", "Reply with exactly: OK", "--model", model,
                 "--max-turns", "1"],
                env={**creds, "PATH": agent_path()},
                capture_output=True, timeout=120, text=True)
            ok = r.returncode == 0
            if not ok:
                err = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
                log.warning("probe %s failed code=%s: %s", model, r.returncode, err or "(no output)")
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("probe %s could not run: %s", model, e)
            ok = False
        # Success only: a later /dispatch or Console refresh must be allowed
        # to retry after a placeholder key failed the first probe.
        if ok:
            cache[model] = True
        return ok

    return probe
