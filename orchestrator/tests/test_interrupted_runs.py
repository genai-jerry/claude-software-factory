"""A run whose process died is closed on the next startup, not left running forever."""

from factory_orchestrator.main import INTERRUPTED, close_interrupted_runs

from .test_graph import ConfiguredRepo, graph_with, issue


def test_ledger_closes_only_unfinished_runs(tmp_path):
    world = ConfiguredRepo({5: issue(5, "x", [])})
    _, engine, ledger, _ = graph_with(tmp_path, world, {})
    live = ledger.start_run(repo="o/r", issue=5, role="profiler", trigger="push:")
    done = ledger.start_run(repo="o/r", issue=5, role="intake", trigger="issues:opened")
    ledger.finish_run(done, outcome="success")

    closed = ledger.interrupt_unfinished("gone")
    assert [r["id"] for r in closed] == [live]
    assert ledger.get_run(live)["outcome"] == "error"
    assert ledger.get_run(live)["finished_at"] is not None
    assert ledger.get_run(done)["outcome"] == "success"
    assert ledger.list_runs(active_only=True) == []
    assert ledger.interrupt_unfinished("gone") == []          # idempotent


def test_startup_closes_the_run_and_says_so_on_the_issue(tmp_path):
    world = ConfiguredRepo({61: issue(61, "Factory: repo profile",
                                      ["factory:profile", "factory:in-progress"])})
    _, engine, ledger, _ = graph_with(tmp_path, world, {})
    run = ledger.start_run(repo="o/r", issue=61, role="profiler", trigger="push:")

    assert close_interrupted_runs(engine, ledger) == 1
    assert ledger.get_run(run)["error"] == INTERRUPTED
    assert "factory:in-progress" not in world.labels_of(61)
    bodies = [c["body"] for c in world.comments.get(61, [])]
    assert any("restarted" in b and f"/runs/{run}" in b for b in bodies)


def test_a_github_failure_still_leaves_the_ledger_right(tmp_path):
    class Down(ConfiguredRepo):
        def create_comment(self, n, body):
            raise RuntimeError("no token yet")

        def remove_label(self, n, label):
            raise RuntimeError("no token yet")

    world = Down({61: issue(61, "Factory: repo profile", ["factory:profile"])})
    _, engine, ledger, _ = graph_with(tmp_path, world, {})
    run = ledger.start_run(repo="o/r", issue=61, role="profiler", trigger="push:")
    assert close_interrupted_runs(engine, ledger) == 1
    assert ledger.get_run(run)["outcome"] == "error"
