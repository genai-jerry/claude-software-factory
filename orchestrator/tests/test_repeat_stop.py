"""A role that keeps ending where it began is not re-run by itself.

10-11 Nov 2026: the Release Manager on expedited tasks commented "a person
must merge this" and left each task at factory:ready-to-ship; expedite and the
release → dispatch chain started it again two minutes later, for five hours
(560 runs). After REPEAT_LIMIT such runs the chain and the reconciler stop,
say so once on the issue, and a person starting the role still can.
"""

import datetime as dt
import json

from factory_orchestrator.graph import Processor
from factory_orchestrator.guards import REPEAT_LIMIT, REPEAT_MARK, repeating
from factory_orchestrator.reconcile import stalled_role

from .test_graph import SystemTestsRepo, graph_with, issue


class EpicBranchRepo(SystemTestsRepo):
    """Epic branches on: a task at ready-to-ship is assembled by the Release Manager."""

    files = {**SystemTestsRepo.files,
             ".github/factory-branches.json": json.dumps({"staging": "staging", "epics": True})}

STUCK = "**You need to:** merge PR #29 into the epic branch.\n\n<!-- factory-agent -->"


def run(role, before, after, outcome="success", minutes=0):
    t = dt.datetime(2026, 11, 11, 0, 0, tzinfo=dt.UTC) - dt.timedelta(minutes=minutes)
    return {"role": role, "outcome": outcome, "started_at": t, "finished_at": t,
            "guards": json.dumps({"before": {"comments": 1, "state": before}, "after_state": after})}


def test_two_runs_that_changed_nothing_are_repeating():
    same = "factory:ready-to-ship"
    assert repeating([run("release", same, same), run("release", same, same, minutes=2)], "release")
    # One is not enough; a run that moved the state, failed, or predates the reading is not one.
    assert not repeating([run("release", same, same)], "release")
    assert not repeating([run("release", same, same), run("release", same, "factory:on-epic", minutes=2)], "release")
    assert not repeating([run("release", same, same), run("release", same, same, outcome="error", minutes=2)], "release")
    old = run("release", same, same, minutes=2)
    old["guards"] = json.dumps({"before": {"state": same}})
    assert not repeating([run("release", same, same), old], "release")
    # Other roles' runs on the issue do not count, and the Dispatcher's work is on its tasks.
    assert not repeating([run("release", same, same), run("qa", same, same, minutes=1)], "release")
    assert not repeating([run("dispatch", same, same), run("dispatch", same, same, minutes=2)], "dispatch")


def _stuck_world():
    task = issue(12, "task(9) Test data loader", ["factory:ready-to-ship"])
    task["body"] = "Part of o/r#9"
    return EpicBranchRepo({
        9: issue(9, "Epic", ["factory:design-approved", "factory:expedite"]),
        12: task,
    })


def test_the_chain_stops_re_running_a_release_that_changes_nothing(tmp_path):
    world = _stuck_world()
    graph, engine, ledger, runner = graph_with(tmp_path, world, {
        "release": lambda w, n: w.create_comment(n, STUCK),
        "dispatch": lambda w, n: w.create_comment(n, "nothing new to release\n\n<!-- factory-agent -->"),
    })
    Processor(engine, graph)("workflow_dispatch", {
        "inputs": {"role": "release", "issue_number": "12"},
        "repository": {"full_name": "o/r"}})
    releases = [c for c in runner.calls if c["role"] == "release"]
    assert len(releases) == REPEAT_LIMIT
    assert len(runner.calls) <= 2 * REPEAT_LIMIT + 1
    notices = [c for c in world.comments[12] if REPEAT_MARK in c["body"]]
    assert len(notices) == 1 and "**release**" in notices[0]["body"] and "You need to:" in notices[0]["body"]

    # A person starting it again is not blocked, and the notice is not repeated.
    before = len(runner.calls)
    Processor(engine, graph)("workflow_dispatch", {
        "inputs": {"role": "release", "issue_number": "12"},
        "repository": {"full_name": "o/r"}})
    assert runner.calls[before]["role"] == "release"
    assert sum(REPEAT_MARK in c["body"] for c in world.comments[12]) == 1


def test_a_release_that_lands_the_task_keeps_chaining(tmp_path):
    world = _stuck_world()

    def lands(w, n):
        w.remove_label(n, "factory:ready-to-ship")
        w.add_labels(n, ["factory:on-epic"])
        w.create_comment(n, "merged onto the epic branch\n\n<!-- factory-agent -->")
    graph, engine, ledger, runner = graph_with(tmp_path, world, {
        "release": lands,
        "dispatch": lambda w, n: w.create_comment(n, "released\n\n<!-- factory-agent -->"),
    })
    Processor(engine, graph)("workflow_dispatch", {
        "inputs": {"role": "release", "issue_number": "12"},
        "repository": {"full_name": "o/r"}})
    assert [c["role"] for c in runner.calls][:2] == ["release", "dispatch"]
    assert not any(REPEAT_MARK in c["body"] for c in world.comments[12])


def test_the_sweep_does_not_restart_it_either():
    world = _stuck_world()
    same = "factory:ready-to-ship"
    now = dt.datetime(2026, 11, 11, 3, 0, tzinfo=dt.UTC)
    runs = [run("release", same, same, minutes=0), run("release", same, same, minutes=2)]
    labels = ["factory:ready-to-ship"]
    got = stalled_role(world, world.issues[12], labels, runs, True, None, now)
    assert got is None
    assert sum(REPEAT_MARK in c["body"] for c in world.comments.get(12, [])) == 1
