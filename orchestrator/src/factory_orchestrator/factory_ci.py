"""The factory as a repo's CI (FACTORY.md §6c).

A repo that sets `"ci": "factory"` in `.github/factory-orchestrator.json` does
not use GitHub Actions to prove a PR's tests pass: the QA run already executes
the profile's `commands.test` in the factory's own workspace, and that run is
the evidence. What GitHub needs is a check it can show and a branch rule can
require, so after every QA run the orchestrator posts a commit status,
`factory/tests`, on the PR's head commit.

The status follows the state QA left the task in, read from GitHub after the
run (the engine contract): `factory:ready-to-ship` is green, a return to
`factory:ready` is red, and anything else (blocked, a failed run) posts
nothing, because QA did not reach a verdict. The orchestrator posts it, not
the agent, so no model ever holds the pen for a green check.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .claim import orchestrator_settings
from .github_app import RepoPort

log = logging.getLogger("factory-orchestrator.ci")

CI_CONTEXT = "factory/tests"
CI_MODES = ("actions", "factory")
READY_TO_SHIP = "factory:ready-to-ship"
READY = "factory:ready"

_CLOSES = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{n}\b"


def ci_mode(port: RepoPort) -> str:
    """`actions` (the default) unless the repo opts into `factory`."""
    mode = orchestrator_settings(port).get("ci")
    return mode if mode in CI_MODES else "actions"


def find_task_pr(port: RepoPort, issue: int) -> dict[str, Any] | None:
    """The open PR for task `issue`: its `factory/<n>-` branch, or `Closes #n`.

    QA may also be handed the PR itself, in which case that PR is the answer.
    """
    pulls = port.list_pulls()
    for pr in pulls:
        if pr.get("number") == issue:
            return pr
    closes = re.compile(_CLOSES.format(n=issue))
    for pr in pulls:
        if ((pr.get("head") or {}).get("ref") or "").startswith(f"factory/{issue}-"):
            return pr
    for pr in pulls:
        if closes.search(pr.get("body") or ""):
            return pr
    return None


def verdict_of(labels: list[str]) -> tuple[str, str] | None:
    """(status state, description) for the labels QA left, or None for no verdict."""
    if "factory:blocked" in labels:
        return None
    if READY_TO_SHIP in labels:
        return "success", "QA ran the tests in the factory: passed"
    if READY in labels:
        return "failure", "QA ran the tests in the factory: a scenario fails"
    return None


def post_qa_status(port: RepoPort, issue: int, run_url: str) -> str | None:
    """Post `factory/tests` for the QA run that just ended; the state posted, or None.

    Best-effort like every guard: a status that did not post must never fail
    the run. It is safe to retry, since GitHub keeps the latest per context.
    """
    try:
        if ci_mode(port) != "factory":
            return None
        iss = port.get_issue(issue) or {}
        labels = [(l if isinstance(l, str) else l.get("name"))
                  for l in iss.get("labels", [])]
        verdict = verdict_of(labels)
        if verdict is None:
            log.info("QA left #%s without a verdict - no %s status", issue, CI_CONTEXT)
            return None
        pr = find_task_pr(port, issue)
        sha = ((pr or {}).get("head") or {}).get("sha")
        if not sha:
            log.warning("no open PR found for #%s - cannot post %s", issue, CI_CONTEXT)
            return None
        state, description = verdict
        port.create_status(sha, state, context=CI_CONTEXT,
                           description=description, target_url=run_url)
        log.info("posted %s=%s on %s/%s PR #%s (%s)", CI_CONTEXT, state,
                 port.owner, port.repo, pr.get("number"), sha[:7])
        return state
    except Exception:  # noqa: BLE001 - a missing status must not fail a good run
        log.warning("could not post %s for #%s", CI_CONTEXT, issue, exc_info=True)
        return None
