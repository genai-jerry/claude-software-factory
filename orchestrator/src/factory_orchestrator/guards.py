"""The run-lifecycle guards from the engine contract.

Each was a real stall in the Actions engine before it was a guard (wiki:
Control-Architecture): the in-progress marker makes a live run visible on
the issue; the no-op guard fails a run that left no visible trace; the
failure report puts the "where do I look" link on the issue thread. All
comments carry the agent marker so they can never self-trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .github_app import RepoPort
from .router import AGENT_MARK, IN_PROGRESS

log = logging.getLogger("factory-orchestrator.guards")


def mark_in_progress(port: RepoPort, issue: int) -> None:
    """Best-effort, like the Actions step: failing to label must never fail a run."""
    try:
        port.add_labels(issue, [IN_PROGRESS])
    except Exception:  # noqa: BLE001
        log.warning("could not mark #%s in progress", issue, exc_info=True)


def clear_in_progress(port: RepoPort, issue: int) -> None:
    """Must run whatever the outcome — a marker that outlives its run lies."""
    try:
        port.remove_label(issue, IN_PROGRESS)
    except Exception:  # noqa: BLE001
        log.warning("could not clear the in-progress marker on #%s", issue, exc_info=True)


@dataclass
class Snapshot:
    comments: int
    state: str  # sorted factory:* labels minus the in-progress marker


def snapshot(port: RepoPort, issue: int) -> Snapshot:
    """Comment count + factory state, the same shape the Actions no-op guard hashes."""
    iss = port.get_issue(issue) or {}
    labels = sorted(
        (l if isinstance(l, str) else l.get("name"))
        for l in iss.get("labels", [])
        if (l if isinstance(l, str) else l.get("name", "")).startswith("factory:")
    )
    labels = [x for x in labels if x != IN_PROGRESS]
    return Snapshot(comments=len(port.list_comments(issue)), state=",".join(labels))


def verify_no_op(port: RepoPort, issue: int, before: Snapshot, role: str) -> bool:
    """True when the role left a visible trace. A run that says nothing did nothing."""
    after = snapshot(port, issue)
    if after.comments != before.comments or after.state != before.state:
        log.info("Role '%s' left a trace on #%s.", role, issue)
        return True
    log.error("Role '%s' finished but changed nothing on #%s - "
              "no factory:* label change and no new comment.", role, issue)
    return False


def report_failure(port: RepoPort, issue: int, role: str, run_url: str) -> None:
    """The failure has to say so where humans look: the issue thread."""
    try:
        port.create_comment(issue, (
            f"⚠️ The **{role}** run failed — [open the run log]({run_url}) for the reason "
            "(missing credentials, tool permission denials, and the turn limit are the "
            "usual ones). Work it completed before failing may still have landed — check "
            "this thread and any PR it links before re-triggering, so a re-run doesn't "
            "redo delivered work.\n\n"
            f"{AGENT_MARK}"))
    except Exception:  # noqa: BLE001 - failing to report must not mask the failure
        log.warning("could not report the failed %s run on #%s", role, issue, exc_info=True)
