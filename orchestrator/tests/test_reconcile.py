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



def expedited_epic_world(*tasks):
    """An epic whose dispatcher has already run, plus the tasks it released."""
    issues = {5: issue(5, "Epic", ["factory:design-approved", "factory:expedite"])}
    for t in tasks:
        issues.update(t)
    return FakeRepo(issues)


def dispatched(ledger):
    """The epic's own dispatch run, so the sweep looks past it to the tasks."""
    ledger.start_run(repo="o/r", issue=5, role="dispatch", trigger="issues:labeled")
    return ledger


def test_sweep_queues_expedited_task_parked_at_ready(tmp_path):
    # The one lost delivery that is silent *and* terminal: expedite already
    # gave the implementation click, so nobody is coming to press it.
    world = expedited_epic_world({8: issue(8, "task(5) do the thing", ["factory:ready"])})
    ledger = dispatched(make_ledger(tmp_path))
    assert sweep_repo(world, ledger) == 1
    [claimed] = ledger.claim_pending()
    assert claimed["payload"]["label"]["name"] == "factory:ready"
    assert claimed["payload"]["issue"]["number"] == 8


def test_sweep_leaves_unexpedited_ready_task_alone(tmp_path):
    # Without the marker, factory:ready is waiting on a human by design.
    world = FakeRepo({5: issue(5, "Epic", ["factory:design-approved"]),
                      8: issue(8, "task(5) do the thing", ["factory:ready"])})
    assert sweep_repo(world, dispatched(make_ledger(tmp_path))) == 0


def test_sweep_leaves_running_or_blocked_expedited_tasks_alone(tmp_path):
    world = expedited_epic_world(
        {8: issue(8, "task(5) running", ["factory:ready", "factory:in-progress"])},
        {9: issue(9, "task(5) blocked", ["factory:ready", "factory:blocked"])})
    assert sweep_repo(world, dispatched(make_ledger(tmp_path))) == 0


def test_sweep_skips_expedited_task_that_already_ran(tmp_path):
    world = expedited_epic_world({8: issue(8, "task(5) do the thing", ["factory:ready"])})
    ledger = dispatched(make_ledger(tmp_path))
    ledger.start_run(repo="o/r", issue=8, role="implementer", trigger="issues:labeled")
    assert sweep_repo(world, ledger) == 0


def cross_repo_world():
    """A task in a sibling repo whose expedited epic lives elsewhere (§7)."""
    tasks = FakeRepo({8: {"number": 8, "title": "task(5) the screen",
                          "body": "Part of o/backend#5",
                          "labels": [{"name": "factory:ready"}],
                          "user": {"type": "Bot"}, "state": "open",
                          "milestone": None}},
                     {}, owner="o", repo="ui")
    epic = FakeRepo({5: issue(5, "Epic", ["factory:design-approved", "factory:expedite"])},
                    {}, owner="o", repo="backend")
    return tasks, epic


def test_sweep_queues_a_cross_repo_expedited_task(tmp_path):
    # The stall this closes: the marker is on an epic in another repo, so
    # deciding whether the task is expedited needs a port over there. Without
    # one the sweep read it as un-expedited and left it parked for good —
    # while the notice on the issue asked for a click expedite had waived.
    tasks, epic = cross_repo_world()
    ledger = make_ledger(tmp_path)
    assert sweep_repo(tasks, ledger, port_for=lambda o, r: epic) == 1
    [claimed] = ledger.claim_pending()
    assert claimed["payload"]["label"]["name"] == "factory:ready"
    assert claimed["payload"]["issue"]["number"] == 8
    assert claimed["payload"]["repository"]["full_name"] == "o/ui"


def test_sweep_without_cross_repo_access_leaves_the_task_alone(tmp_path):
    # Unchanged, and deliberate: an epic this engine cannot read is not an
    # expedited one, and asking a human is the safe way to be wrong.
    tasks, _epic = cross_repo_world()
    assert sweep_repo(tasks, make_ledger(tmp_path)) == 0
