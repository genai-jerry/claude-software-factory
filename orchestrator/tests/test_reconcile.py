from factory_orchestrator.ledger import Ledger
from factory_orchestrator.reconcile import sweep_repo

from .fake_repo import FakeRepo
from .test_graph import issue


def make_ledger(tmp_path):
    return Ledger(f"sqlite:///{tmp_path}/r.db")


def test_sweep_queues_missed_gate_approval(tmp_path):
    # G1 was approved while the orchestrator was down: spec-approved with no
    # recorded run. The sweep synthesizes the labeled event the webhook missed.
    world = FakeRepo({5: issue(5, "Epic", ["factory:spec-approved"])})
    ledger = make_ledger(tmp_path)
    assert sweep_repo(world, ledger) == 1
    [claimed] = ledger.claim_pending()
    assert claimed["event"] == "issues"
    assert claimed["payload"]["action"] == "labeled"
    assert claimed["payload"]["label"]["name"] == "factory:spec-approved"
    assert claimed["payload"]["issue"]["number"] == 5


def test_sweep_skips_issue_with_recorded_run(tmp_path):
    world = FakeRepo({5: issue(5, "Epic", ["factory:spec-approved"])})
    ledger = make_ledger(tmp_path)
    ledger.start_run(repo="o/r", issue=5, role="planner", trigger="issues:labeled")
    assert sweep_repo(world, ledger) == 0


def test_sweep_queues_undispatched_release(tmp_path):
    ms = {"number": 7, "title": "v0.4", "html_url": "u"}
    world = FakeRepo({1: issue(1, "release(7): v0.4",
                               ["factory:release", "factory:release-approved"],
                               user="Bot", milestone=ms)})
    ledger = make_ledger(tmp_path)
    assert sweep_repo(world, ledger) == 1


def test_sweep_skips_dispatched_release(tmp_path):
    ms = {"number": 7, "title": "v0.4", "html_url": "u"}
    world = FakeRepo(
        {1: issue(1, "release(7): v0.4", ["factory:release", "factory:release-approved"],
                  user="Bot", milestone=ms)},
        {1: [{"body": "done\n\n<!-- factory-release-dispatched -->"}]})
    ledger = make_ledger(tmp_path)
    assert sweep_repo(world, ledger) == 0


def test_sweep_ignores_states_without_pending_steps(tmp_path):
    world = FakeRepo({5: issue(5, "Epic", ["factory:in-review"]),
                      6: issue(6, "Epic2", ["factory:spec-ready"])})
    assert sweep_repo(world, make_ledger(tmp_path)) == 0


def test_sweep_queues_idle_fast_track(tmp_path):
    world = FakeRepo({102: issue(102, "Add a FACTORY_CANARY.md", ["factory:fast-track"])})
    ledger = make_ledger(tmp_path)
    assert sweep_repo(world, ledger) == 1
    [claimed] = ledger.claim_pending()
    assert claimed["payload"]["label"]["name"] == "factory:fast-track"
    assert claimed["payload"]["issue"]["number"] == 102


def test_sweep_skips_fast_track_with_recorded_run(tmp_path):
    world = FakeRepo({102: issue(102, "Canary", ["factory:fast-track"])})
    ledger = make_ledger(tmp_path)
    ledger.start_run(repo="o/r", issue=102, role="fasttrack", trigger="issues:labeled")
    assert sweep_repo(world, ledger) == 0
