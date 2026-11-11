"""The run-lifecycle guards from the engine contract.

Each was a real stall in the Actions engine before it was a guard (wiki:
Control-Architecture): the in-progress marker makes a live run visible on
the issue; the no-op guard fails a run that left no visible trace; the
failure report puts the "where do I look" link on the issue thread. All
comments carry the agent marker so they can never self-trigger.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from .github_app import RepoPort, parse_json_or_empty
from .next_step import (
    GATE_OF_STATE,
    already_said,
    approvers_for,
    extract_questions,
    load_table,
    newest_agent_question_body,
    render,
    state_of,
)
from .router import AGENT_MARK, IN_PROGRESS, is_expedited

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


def factory_state(port: RepoPort, issue: int) -> str:
    """The issue's factory state: its sorted factory:* labels minus the in-progress marker."""
    iss = port.get_issue(issue) or {}
    labels = sorted(
        (l if isinstance(l, str) else l.get("name"))
        for l in iss.get("labels", [])
        if (l if isinstance(l, str) else l.get("name", "")).startswith("factory:")
    )
    return ",".join(x for x in labels if x != IN_PROGRESS)


def snapshot(port: RepoPort, issue: int) -> Snapshot:
    """Comment count + factory state, the same shape the Actions no-op guard hashes."""
    return Snapshot(comments=len(port.list_comments(issue)), state=factory_state(port, issue))


# --- runs that change nothing ------------------------------------------------
#
# A run that only comments is a success to the no-op guard, and the chain and
# the reconciler then start the same role again on the same unchanged state.
# On 10-11 Nov 2026 the Release Manager on four beacon-api tasks and two
# beacon-whatsapp tasks did that for five hours — each run said "a person must
# merge this", each was re-run two minutes later — 560 runs, $377. After this
# many such runs in a row, nothing starts that role on that issue by itself
# again; a person starting it (Compass, a label) still does.

REPEAT_LIMIT = 2
REPEAT_MARK = "<!-- factory-repeat-stop -->"
#: Roles whose work lands on other issues, so an unchanged state of their own is normal.
REPEAT_EXEMPT = frozenset({"dispatch"})


def _guards_of(run: dict) -> dict:
    g = run.get("guards")
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except ValueError:
            return {}
    return g if isinstance(g, dict) else {}


def repeating(runs: list[dict], role: str) -> bool:
    """True when `role`'s last REPEAT_LIMIT finished runs here all succeeded and left the
    issue's state as they found it. `runs` is the issue's ledger rows, newest first."""
    if role in REPEAT_EXEMPT:
        return False
    mine = [r for r in runs if r.get("role") == role and r.get("finished_at") is not None][:REPEAT_LIMIT]
    if len(mine) < REPEAT_LIMIT:
        return False
    for r in mine:
        g = _guards_of(r)
        before = (g.get("before") or {}).get("state")
        after = g.get("after_state")
        if r.get("outcome") != "success" or before is None or after is None or before != after:
            return False
    return True


def report_repeat_stop(port: RepoPort, issue: int, role: str) -> bool:
    """Say once, on the issue, that the factory stopped re-running this role. True if posted."""
    try:
        recent = port.list_comments(issue)[-10:]
        if any(REPEAT_MARK in (c.get("body") or "") and f"**{role}**" in (c.get("body") or "") for c in recent):
            return False
        port.create_comment(issue, (
            f"**The factory stopped re-running the **{role}** here: its last {REPEAT_LIMIT} runs "
            "changed nothing.** Each one ended with the same state it started from.\n\n"
            "**You need to:** do what its last comment asks, then start it again from Compass. "
            "Nothing starts it on this issue by itself until then.\n\n"
            f"{REPEAT_MARK}\n{AGENT_MARK}"))
        log.warning("stopped re-running %s on %s/%s#%s: %d runs changed nothing",
                    role, port.owner, port.repo, issue, REPEAT_LIMIT)
        return True
    except Exception:  # noqa: BLE001 - a missing notice must not fail the chain
        log.warning("could not report the repeat stop on #%s", issue, exc_info=True)
        return False


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


def report_staging_moved(port: RepoPort, issue: int, role: str, branch: str, run_url: str) -> None:
    """`branch` changed during a run with no release-to-staging approval."""
    log.error("%s moved during the %s run on #%s", branch, role, issue)
    try:
        port.create_comment(issue, (
            f"**`{branch}` changed during this {role} run, with no release to staging (GS) "
            "behind it.**\n"
            "**You need to:** check what landed. If a person merged it, nothing is wrong.\n"
            f"- The run should not write to `{branch}`, and the guard did not stop this.\n"
            f"Links: [the run]({run_url})\n\n"
            f"{AGENT_MARK}"))
    except Exception:  # noqa: BLE001 - the ledger already records it
        log.warning("could not report the moved %s on #%s", branch, issue, exc_info=True)


def report_next_step(port: RepoPort, issue: int, role: str, factory_checkout,
                     port_for: Callable[[str, str], RepoPort] | None = None) -> None:
    """Say what the next actor is expected to do, on the issue, after the run.

    Called only on the success path: a failed run already has its own report,
    and a hand-off notice under it would name a state the role never reached.
    Best-effort like every other notice here — a run that worked must not be
    reported as failed because a comment did not post.

    `port_for` is what lets the expedite check read an epic in another repo
    (FACTORY.md §7). Without it a cross-repo task reads as un-expedited and
    this notice names an approver and asks for a click expedite already
    waived — the Actions engine's twin (scripts/say_next_step.py) does the
    cross-repo read over its PAT, and this one has to match it.
    """
    table = load_table(factory_checkout)
    if table is None:
        return
    try:
        iss = port.get_issue(issue) or {}
        labels = [(l if isinstance(l, str) else l.get("name"))
                  for l in iss.get("labels", [])]
        state = state_of(labels)
        comments = port.list_comments(issue)
        if already_said(comments, state):
            log.info("#%s already carries the hand-off notice for %s", issue, state)
            return
        # A blocked issue's notice repeats the role's questions, so the last
        # thing on the thread is what the person has to answer.
        questions = extract_questions(newest_agent_question_body(comments)) \
            if state == "factory:blocked" else []
        approvers = []
        if GATE_OF_STATE.get(state or ""):
            cfg = parse_json_or_empty(port.get_file(".github/factory-approvers.json"))
            approvers = approvers_for(state, cfg)
        expedited = is_expedited(port, iss, port_for)
        # The repo's system-test policy (FACTORY.md §4b) selects the `tested`
        # wording for the two states whose story it changes. Read here rather
        # than passed in, so every caller of this guard gets it right.
        tested = parse_json_or_empty(
            port.get_file(".github/factory-testing.json")).get("system_tests") is True
        port.create_comment(
            issue,
            f"{render(table, role, issue, state, approvers, expedited, tested, questions)}\n{AGENT_MARK}")
        log.info("said what happens next on #%s (%s)", issue, state or "no state")
    except Exception:  # noqa: BLE001 - a missing notice must not fail a good run
        log.warning("could not post the hand-off notice on #%s", issue, exc_info=True)
