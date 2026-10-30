"""Idle issues the reconciler restarts (reconcile.stalled_role) and the
restart's own stand-down when the issue moved on (Router, expect_state)."""

from __future__ import annotations

import datetime as dt

from factory_orchestrator.reconcile import (
    limit_resets_at,
    stalled_role,
    sweep_repo,
    usage_limit_error,
)
from factory_orchestrator.router import RepoConfig, Router

from .test_graph import APPROVERS, ConfiguredRepo, issue
from .test_reconcile import make_ledger

NOW = dt.datetime(2026, 10, 30, 15, 0, tzinfo=dt.UTC)
INTERRUPTED = "Interrupted: the orchestrator restarted while this run was in progress."
LIMIT = usage_limit_error("You've hit your session limit · resets 2:50pm (UTC)")


def run(role, outcome="success", error=None, mins_ago=60, rid=None):
    return {"id": rid or f"{role}-{mins_ago}", "role": role, "outcome": outcome,
            "error": error, "finished_at": NOW - dt.timedelta(minutes=mins_ago)}


class Expedited(ConfiguredRepo):
    """Epic #5 is expedited; its tasks find it through `task(5)`."""


def world(task_labels, epic_labels=("factory:design-approved", "factory:expedite")):
    return Expedited({5: issue(5, "Epic", list(epic_labels)),
                      14: issue(14, "task(5): retry reads", list(task_labels))})


def stalled(w, runs, epics=True):
    i = w.issues[14]
    return stalled_role(w, i, w.labels_of(14), runs, epics, None, NOW)


def test_usage_limit_is_named_and_its_reset_read():
    assert "Claude usage limit reached" in LIMIT and "resets 2:50pm (UTC)" in LIMIT
    assert usage_limit_error("Claude exited 1.") is None
    finished = dt.datetime(2026, 10, 30, 14, 43, tzinfo=dt.UTC)
    assert limit_resets_at(LIMIT, finished) == finished.replace(hour=14, minute=50)
    late = dt.datetime(2026, 10, 30, 23, 0, tzinfo=dt.UTC)
    assert limit_resets_at(LIMIT, late).day == 31


def test_an_interrupted_qa_is_restarted_after_the_grace():
    # beacon-api#63: QA cut off by a restart, then nothing for hours.
    w = world(["factory:in-test"])
    assert stalled(w, [run("qa", "error", INTERRUPTED, mins_ago=30)]) == ("qa", "factory:in-test")
    assert stalled(w, [run("qa", "error", INTERRUPTED, mins_ago=2)]) is None


def test_a_usage_limit_waits_for_the_reset():
    w = world(["factory:in-review"])
    before = [run("reviewer", "error", LIMIT, mins_ago=20)]   # finished 14:40, resets 14:50
    assert stalled(w, before) == ("reviewer", "factory:in-review")
    not_yet = [{**before[0], "finished_at": NOW.replace(hour=14, minute=45)}]
    assert stalled_role(w, w.issues[14], w.labels_of(14), not_yet, True, None,
                        NOW.replace(hour=14, minute=48)) is None


def test_genuine_failures_retry_twice_then_wait_for_a_human():
    w = world(["factory:in-test"])
    two = [run("qa", "error", "Claude exited 1.", 30, "b"),
           run("qa", "error", "Claude exited 1.", 60, "a")]
    assert stalled(w, two) == ("qa", "factory:in-test")
    three = [run("qa", "error", "Claude exited 1.", 15, "c"), *two]
    assert stalled(w, three) is None


def test_an_expedited_task_past_ready_is_started():
    # beacon-connectors#14: in review for ten hours, no reviewer ever ran.
    w = world(["factory:in-review"])
    assert stalled(w, [run("implementer", mins_ago=600)]) == ("reviewer", "factory:in-review")
    assert stalled(w, [run("implementer", mins_ago=5)]) is None  # chain may still be moving


def test_ready_to_ship_ships_only_onto_an_epic_branch():
    w = world(["factory:ready-to-ship"])
    assert stalled(w, [run("qa")]) == ("release", "factory:ready-to-ship")
    assert stalled(w, [run("qa")], epics=False) is None


def test_nothing_is_restarted_that_a_human_owns():
    assert stalled(world(["factory:in-review"], ["factory:design-approved"]),
                   [run("implementer", mins_ago=600)]) is None          # not expedited
    assert stalled(world(["factory:in-test", "factory:blocked"]),
                   [run("qa", "error", INTERRUPTED)]) is None
    assert stalled(world(["factory:in-test", "factory:in-progress"]),
                   [run("qa", "error", INTERRUPTED)]) is None
    live = [{**run("qa"), "finished_at": None}]
    assert stalled(world(["factory:in-test"]), live) is None
    assert stalled(world(["factory:in-test"]), []) is None


def test_a_failed_run_that_moved_the_issue_is_not_repeated():
    # The reviewer flipped the label, then died: re-running it would review twice.
    w = world(["factory:in-test"], ["factory:design-approved"])
    assert stalled(w, [run("reviewer", "error", INTERRUPTED)]) is None


def test_the_sweep_queues_one_restart_per_stalled_run(tmp_path):
    w = world(["factory:in-test"])
    ledger = make_ledger(tmp_path)
    ledger.finish_run(ledger.start_run(repo="o/r", issue=5, role="dispatch", trigger="t"),
                      outcome="success")
    rid = ledger.start_run(repo="o/r", issue=14, role="qa", trigger="t")
    ledger.finish_run(rid, outcome="error", error=INTERRUPTED)
    with ledger.engine.begin() as cx:  # pretend it all ended half an hour ago
        from factory_orchestrator.ledger import runs
        cx.execute(runs.update().values(
            finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)))
    assert sweep_repo(w, ledger) == 1
    assert sweep_repo(w, ledger) == 0
    [d] = ledger.claim_pending()
    assert d["event"] == "workflow_dispatch"
    assert d["payload"]["inputs"] == {"role": "qa", "issue_number": 14,
                                      "expect_state": "factory:in-test"}


def _dispatch(w, expect):
    return Router(w, RepoConfig(approvers=APPROVERS)).route("workflow_dispatch", {
        "inputs": {"role": "qa", "issue_number": 14, "expect_state": expect},
        "repository": {"full_name": "o/r"}})


def test_a_restart_stands_down_when_the_issue_moved_on():
    assert _dispatch(world(["factory:in-test"]), "factory:in-test").role == "qa"
    assert _dispatch(world(["factory:ready-to-ship"]), "factory:in-test").role == "none"
    assert _dispatch(world(["factory:in-test", "factory:in-progress"]),
                     "factory:in-test").role == "none"
    w = world(["factory:in-test"])
    assert Router(w, RepoConfig(approvers=APPROVERS)).route("workflow_dispatch", {
        "inputs": {"role": "qa", "issue_number": 14},
        "repository": {"full_name": "o/r"}}).role == "qa"  # an operator's dispatch: unchanged


