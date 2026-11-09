"""A fast-lane fix goes onto staging once it is green (FACTORY.md §5) — beacon-api#379
sat open for hours waiting for a person to merge it."""

from __future__ import annotations

from factory_orchestrator.fast_track_merge import HELD_MARK, MERGED_MARK, merge_fast_track
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.reconcile import sweep_repo

from .fake_repo import FakeRepo
from .test_graph import issue


def world(pr_over=None, state=None):
    w = FakeRepo({377: issue(377, "A lead's reply is lost when its flow is gone", ["factory:fast-track"])})
    pr = {"number": 379, "head": {"ref": "factory/377-reply-when-flow-is-gone"}, "base": {"ref": "staging"},
          "body": "Closes #377\n\nBase branch: staging", **(pr_over or {})}
    w.open_prs["o:factory/377-reply-when-flow-is-gone"] = [pr]
    if state is not None:
        w.pr_states = {379: state}
    return w


def said(w, mark):
    return [c["body"] for c in w.comments.get(377, []) if mark in c["body"]]


def test_a_green_fast_lane_pr_is_merged_onto_staging_and_said_once():
    w = world()
    assert merge_fast_track(w, 377, {}) == "merged"
    assert w.merged_prs == [379] and w.merged_bases[379] == "staging"
    assert len(said(w, MERGED_MARK)) == 1
    assert "next promotion PR" in said(w, MERGED_MARK)[0]


def test_running_checks_wait_for_the_next_sweep_without_saying_anything():
    w = world(state={"mergeable": True, "failing": False, "pending": True})
    assert merge_fast_track(w, 377, {}) == "waiting"
    w2 = world(state={"mergeable": None, "failing": False, "pending": False})  # GitHub still computing
    assert merge_fast_track(w2, 377, {}) == "waiting"
    assert w.merged_prs == [] and w.comments.get(377) is None


def test_a_red_or_conflicting_pr_is_held_and_said_once():
    w = world(state={"mergeable": True, "failing": True, "pending": False})
    assert merge_fast_track(w, 377, {}) == "held"
    assert merge_fast_track(w, 377, {}) == "held"
    assert w.merged_prs == [] and len(said(w, HELD_MARK)) == 1
    assert "a check on it failed" in said(w, HELD_MARK)[0]
    c = world(state={"mergeable": False, "failing": False, "pending": False})
    merge_fast_track(c, 377, {})
    assert "no longer merges cleanly" in said(c, HELD_MARK)[0]


def test_never_onto_the_default_branch_and_off_when_the_repo_says_so():
    w = world(pr_over={"base": {"ref": "main"}})
    assert merge_fast_track(w, 377, {}) == "held" and w.merged_prs == []
    assert merge_fast_track(world(), 377, {"fast_track_merge": False}) == "off"


def test_only_the_fast_lanes_own_pr():
    w = world(pr_over={"head": {"ref": "someone/else"}})
    assert merge_fast_track(w, 377, {}) == "none"
    w = world(pr_over={"body": "Closes #3770"})
    assert merge_fast_track(w, 377, {}) == "none"


def test_the_sweep_merges_a_fix_whose_run_succeeded(tmp_path):
    w = world()
    ledger = Ledger(f"sqlite:///{tmp_path}/r.db")
    run = ledger.start_run(repo="o/r", issue=377, role="fasttrack", trigger="issues:labeled")
    ledger.finish_run(run, outcome="success")
    sweep_repo(w, ledger)
    assert w.merged_prs == [379]


def test_the_sweep_leaves_a_fix_whose_run_failed(tmp_path):
    w = world()
    ledger = Ledger(f"sqlite:///{tmp_path}/r.db")
    run = ledger.start_run(repo="o/r", issue=377, role="fasttrack", trigger="issues:labeled")
    ledger.finish_run(run, outcome="error")
    sweep_repo(w, ledger)
    assert w.merged_prs == []
