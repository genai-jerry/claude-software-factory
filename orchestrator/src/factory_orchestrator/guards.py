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

from .github_app import RepoPort, parse_json_or_empty
from .next_step import (
    GATE_OF_STATE,
    already_said,
    load_table,
    render,
    state_of,
)
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


def no_op_reason(role: str, issue: int) -> str:
    """Human reason stored on the run and posted on the issue when the guard trips."""
    return (
        f"Role '{role}' finished but changed nothing on #{issue} — no factory:* "
        "label change and no new comment. Local work in the run workspace is "
        "discarded when the session ends. This is not a credentials, permission, "
        "or turn-limit failure unless the transcript says so."
    )


def verify_no_op(port: RepoPort, issue: int, before: Snapshot, role: str) -> bool:
    """True when the role left a visible trace. A run that says nothing did nothing."""
    after = snapshot(port, issue)
    if after.comments != before.comments or after.state != before.state:
        log.info("Role '%s' left a trace on #%s.", role, issue)
        return True
    log.error("%s", no_op_reason(role, issue))
    return False


def report_start(port: RepoPort, issue: int, role: str, run_url: str) -> None:
    """A live run has to say so where humans look: the issue thread.

    Posted before the no-op snapshot so it is not itself counted as the role's
    trace. The Console (and anyone watching the issue) can follow the log
    without an Actions run.
    """
    try:
        port.create_comment(issue, (
            f"▶ The **{role}** is running under the Software Factory orchestrator — "
            f"[watch the run]({run_url}).\n\n"
            f"{AGENT_MARK}"))
        log.info("posted start comment for %s on #%s log=%s", role, issue, run_url)
    except Exception:  # noqa: BLE001 - a missing start note must not fail the run
        log.warning("could not report the starting %s run on #%s", role, issue, exc_info=True)


def report_failure(port: RepoPort, issue: int, role: str, run_url: str,
                   reason: str | None = None) -> None:
    """The failure has to say so where humans look: the issue thread."""
    why = (reason or "").strip() or (
        "missing credentials, tool permission denials, and the turn limit are the usual ones"
    )
    try:
        port.create_comment(issue, (
            f"⚠️ The **{role}** run failed — [open the run log]({run_url}).\n\n"
            f"{why}\n\n"
            "Work it completed before failing may still have landed — check "
            "this thread and any PR it links before re-triggering, so a re-run "
            "doesn't redo delivered work.\n\n"
            f"{AGENT_MARK}"))
        log.info("posted failure comment for %s on #%s log=%s", role, issue, run_url)
    except Exception:  # noqa: BLE001 - failing to report must not mask the failure
        log.warning("could not report the failed %s run on #%s", role, issue, exc_info=True)


def report_next_step(port: RepoPort, issue: int, role: str, factory_checkout) -> None:
    """Say what the next actor is expected to do, on the issue, after the run.

    Called only on the success path: a failed run already has its own report,
    and a hand-off notice under it would name a state the role never reached.
    Best-effort like every other notice here — a run that worked must not be
    reported as failed because a comment did not post.
    """
    table = load_table(factory_checkout)
    if table is None:
        return
    try:
        iss = port.get_issue(issue) or {}
        labels = [(l if isinstance(l, str) else l.get("name"))
                  for l in iss.get("labels", [])]
        state = state_of(labels)
        if already_said(port.list_comments(issue), state):
            log.info("#%s already carries the hand-off notice for %s", issue, state)
            return
        gate = GATE_OF_STATE.get(state or "")
        approvers = []
        if gate:
            cfg = parse_json_or_empty(port.get_file(".github/factory-approvers.json"))
            value = cfg.get(gate)
            approvers = [x for x in value if isinstance(x, str)] if isinstance(value, list) else []
        port.create_comment(issue, f"{render(table, role, issue, state, approvers)}\n{AGENT_MARK}")
        log.info("said what happens next on #%s (%s)", issue, state or "no state")
    except Exception:  # noqa: BLE001 - a missing notice must not fail a good run
        log.warning("could not post the hand-off notice on #%s", issue, exc_info=True)
