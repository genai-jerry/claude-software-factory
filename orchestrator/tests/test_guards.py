from factory_orchestrator.guards import (
    clear_in_progress,
    mark_in_progress,
    report_failure,
    report_start,
    snapshot,
    verify_no_op,
)
from factory_orchestrator.router import AGENT_MARK

from .fake_repo import FakeRepo


def repo_with_issue():
    return FakeRepo({5: {"number": 5, "title": "Epic",
                         "labels": [{"name": "factory:intake"}],
                         "user": {"type": "User"}, "state": "open", "milestone": None}})


def test_marker_on_and_off():
    w = repo_with_issue()
    mark_in_progress(w, 5)
    assert "factory:in-progress" in w.labels_of(5)
    clear_in_progress(w, 5)
    assert "factory:in-progress" not in w.labels_of(5)


def test_marker_failures_swallowed():
    class Broken(FakeRepo):
        def add_labels(self, n, ls):
            raise RuntimeError("api down")

        def remove_label(self, n, l):
            raise RuntimeError("api down")
    w = Broken({5: {"number": 5, "title": "E", "labels": [], "user": {"type": "User"},
                    "state": "open", "milestone": None}})
    mark_in_progress(w, 5)   # must not raise
    clear_in_progress(w, 5)  # must not raise


def test_snapshot_ignores_in_progress_marker():
    w = repo_with_issue()
    before = snapshot(w, 5)
    mark_in_progress(w, 5)
    assert snapshot(w, 5) == before


def test_no_op_guard_fails_silent_role():
    w = repo_with_issue()
    before = snapshot(w, 5)
    assert not verify_no_op(w, 5, before, "intake")


def test_no_op_guard_passes_on_comment_or_label():
    w = repo_with_issue()
    before = snapshot(w, 5)
    w.create_comment(5, "did a thing")
    assert verify_no_op(w, 5, before, "intake")

    w2 = repo_with_issue()
    before2 = snapshot(w2, 5)
    w2.remove_label(5, "factory:intake")
    w2.add_labels(5, ["factory:spec-ready"])
    assert verify_no_op(w2, 5, before2, "intake")


def test_failure_report_links_run_and_carries_marker():
    w = repo_with_issue()
    report_failure(w, 5, "intake", "https://factory.example/runs/abc")
    body = w.comments[5][0]["body"]
    assert "https://factory.example/runs/abc" in body
    assert "**intake** run failed" in body
    assert AGENT_MARK in body


def test_start_report_links_run_and_carries_marker():
    w = repo_with_issue()
    report_start(w, 5, "profiler", "https://factory.example/runs/abc")
    body = w.comments[5][0]["body"]
    assert "watch the run" in body
    assert "https://factory.example/runs/abc" in body
    assert "**profiler** is running" in body
    assert AGENT_MARK in body
