"""The engine claim (orchestration/engine-selection).

`.github/factory-orchestrator.json` on the consuming repo's default branch
names the engine that drives the repo. This engine acts only when the file
names it; the Actions pipeline stands down only when the file names someone
else. Both sides read the same file when they process an event, so a config
race resolves to at most one engine acting per event — the two checks are
complementary by construction, which test_claim.py asserts against the same
cases the Actions stand-down fixtures pin.
"""

from __future__ import annotations

import logging
from typing import Any

from .github_app import RepoPort, parse_json_or_empty

log = logging.getLogger("factory-orchestrator.claim")

CONFIG_PATH = ".github/factory-orchestrator.json"
DEFAULT_ENGINE = "github-actions"


def declared_engine(port: RepoPort) -> str:
    """The engine the repo declares; absent/invalid config means Actions."""
    text = port.get_file(CONFIG_PATH)
    cfg = parse_json_or_empty(text)
    engine = cfg.get("engine")
    return engine if isinstance(engine, str) and engine else DEFAULT_ENGINE


def claim_check(port: RepoPort, engine_name: str) -> bool:
    """True when this engine holds the claim for the repo."""
    engine = declared_engine(port)
    if engine != engine_name:
        log.info("claim: %s/%s declares engine %r, not %r - dropping the event",
                 port.owner, port.repo, engine, engine_name)
        return False
    log.info("claim: %s/%s accepted for %s", port.owner, port.repo, engine_name)
    return True


def orchestrator_settings(port: RepoPort) -> dict[str, Any]:
    """The engine-facing knobs from the same file (runners, endpoint)."""
    return parse_json_or_empty(port.get_file(CONFIG_PATH))
