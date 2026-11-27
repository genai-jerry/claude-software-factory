"""Simulated runs for a batch of releases (sim_batch.py): hold back while others wait, then one run."""

import threading
from types import SimpleNamespace

import pytest

from factory_orchestrator.graph import start_held_back_run
from factory_orchestrator.issue_workspaces import STAGING, IssueKey
from factory_orchestrator.role_runner import RoleOutcome
from factory_orchestrator.sim_batch import (
    BatchRunError,
    how_to_start,
    later_env,
    says_later,
    start_batch_run,
)

from .fake_repo import FakeRepo
from .test_build_environments import runner_with_environments, wait_for

SIM = {"pack": "beacon/sim/scenarios", "status_context": "beacon/sim-scenarios",
       "run_repo": "genai-jerry/beacon-infra"}
HEAD = "a" * 40


def api_repo(message="Merge release(825)\n\nSim-scenarios: later\n"):
    port = FakeRepo(owner="genai-jerry", repo="beacon-api")
    port.branch_shas["staging"] = HEAD
    port.commit_messages[HEAD] = message
    return port


def test_the_line_must_stand_on_its_own():
    assert says_later("Merge\n\nSim-scenarios: later")
    assert says_later("Merge\n\nsim-scenarios:  LATER \nSigned-off-by: x")
    assert not says_later("Merge\n\nWe wrote Sim-scenarios: later in prose")
    assert not says_later("Merge\n\nSim-scenarios: now")
    assert not says_later(None)


def test_a_release_holds_back_only_with_a_sim_and_others_waiting():
    assert later_env(SIM, 2) == {"FACTORY_SIM_LATER": "1"}
    assert later_env(SIM, 0) == {}
    assert later_env(None, 3) == {}


def test_the_last_release_starts_one_run_in_the_run_repo_for_the_head():
    api, infra = api_repo(), FakeRepo(owner="genai-jerry", repo="beacon-infra")
    started: set[str] = set()
    opened = []

    def port_for(owner, name):
        opened.append(f"{owner}/{name}")
        return infra

    assert start_batch_run(api, SIM, "staging", port_for, started) == HEAD
    assert opened == ["genai-jerry/beacon-infra"]
    assert infra.dispatched == [("sim-scenarios.yml", "main", {"after": f"genai-jerry/beacon-api@{HEAD}"})]
    # One run per head, however many release runs end on it.
    assert start_batch_run(api, SIM, "staging", port_for, started) is None
    assert len(infra.dispatched) == 1


def test_a_head_that_was_not_held_back_started_its_own_run():
    api, infra = api_repo("Merge release(825)\n\nNothing held\n"), FakeRepo()
    assert start_batch_run(api, SIM, "staging", lambda o, n: infra, set()) is None
    assert infra.dispatched == []


def test_nothing_without_a_sim_or_an_integration_branch():
    api = api_repo()
    assert start_batch_run(api, None, "staging", None, set()) is None
    assert start_batch_run(api, SIM, None, None, set()) is None
    api.branch_shas.clear()
    assert start_batch_run(api, SIM, "staging", None, set()) is None


def test_a_run_repo_of_its_own_and_a_workflow_named_in_the_block():
    api = api_repo()
    start_batch_run(api, {**SIM, "run_repo": "", "workflow": "sims.yml"}, "staging", None, set())
    assert api.dispatched == [("sims.yml", "main", {"after": f"genai-jerry/beacon-api@{HEAD}"})]


def test_a_run_that_cannot_be_started_says_how_to_start_it_and_is_not_retried():
    api, started = api_repo(), set()

    def refused(owner, name):
        port = FakeRepo(owner=owner, repo=name)
        port.dispatch_workflow = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Resource not accessible"))
        return port

    with pytest.raises(BatchRunError) as caught:
        start_batch_run(api, SIM, "staging", refused, started)
    assert caught.value.head == HEAD
    assert start_batch_run(api, SIM, "staging", refused, started) is None
    text = how_to_start(api, SIM, HEAD, caught.value.error)
    assert "403 Resource not accessible" in text
    assert f"`genai-jerry/beacon-api@{HEAD}`" in text
    assert "genai-jerry/beacon-infra, Actions > sim-scenarios.yml > Run workflow" in text
    with pytest.raises(BatchRunError):
        start_batch_run(api_repo(), SIM, "staging", None, set())  # no access to the run repo


# ------------------------------------------------------------ the engine's side
class Workspaces:
    def __init__(self, busy=False):
        self._busy = busy

    def busy(self, owner, repo, key):
        return self._busy


def engine_with(port, infra, *, busy=False, simulate=SIM):
    cfg = SimpleNamespace(simulate=simulate, staging_branch="staging")
    return SimpleNamespace(runner=SimpleNamespace(issue_workspaces=Workspaces(busy)),
                           repo_config=lambda p: cfg, port=lambda o, n: infra, sim_batch_started=set())


def test_the_engine_starts_the_run_when_no_release_holds_or_waits():
    api, infra = api_repo(), FakeRepo(owner="genai-jerry", repo="beacon-infra")
    start_held_back_run(engine_with(api, infra), api, 825, STAGING)
    assert len(infra.dispatched) == 1


def test_the_engine_leaves_it_to_the_next_release_while_one_holds_or_waits():
    api, infra = api_repo(), FakeRepo()
    start_held_back_run(engine_with(api, infra, busy=True), api, 825, STAGING)
    start_held_back_run(engine_with(api, infra), api, 825, IssueKey(825))  # not on staging
    start_held_back_run(engine_with(api, infra), api, 825, None)
    assert infra.dispatched == []


def test_the_engine_says_on_the_epic_when_the_run_cannot_start():
    api = api_repo()
    api.issues[825] = {"number": 825, "title": "Epic", "labels": [], "state": "open"}
    engine = engine_with(api, None)
    engine.port = lambda o, n: (_ for _ in ()).throw(RuntimeError("not installed"))
    start_held_back_run(engine, api, 825, STAGING)
    assert "could not start that run (not installed)" in api.comments[825][-1]["body"]


# ------------------------------------------------------------ the runner's side
def release_runner(tmp_path):
    runner, ws, _, _ = runner_with_environments(tmp_path, max_parallel=3)
    (tmp_path / "factory" / "commands" / "release.md").write_text("# Release\nRELEASE BODY\n")
    return runner, ws


def test_a_release_with_others_waiting_for_staging_holds_its_sim_back(tmp_path, monkeypatch):
    runner, ws = release_runner(tmp_path)
    seen: dict[str, dict] = {}

    def session(self, prompt, **kw):
        seen[kw["issue"]] = dict(kw.get("extra_env") or {})
        return RoleOutcome(status="success", transcript="")

    monkeypatch.setattr(type(runner), "_session", session)

    def release(issue, simulate):
        runner.run(owner="o", repo="r", role="release", issue=issue, model="m", github_token="t",
                   workspace=STAGING, run_id=str(issue), simulate=simulate)

    with ws.hold("o", "r", STAGING):
        first = threading.Thread(target=release, args=(1, SIM))
        second = threading.Thread(target=release, args=(2, SIM))
        first.start()
        assert wait_for(lambda: ws.waiting("o", "r", STAGING) == 1)
        second.start()
        assert wait_for(lambda: ws.waiting("o", "r", STAGING) == 2)
        assert ws.busy("o", "r", STAGING)
    for t in (first, second):
        t.join(30)
    assert sorted(seen) == [1, 2]
    # Whichever got the turn first had the other waiting behind it; the last had nobody.
    assert sorted(bool(env) for env in seen.values()) == [False, True]
    assert not ws.busy("o", "r", STAGING)


def test_a_repo_without_a_sim_never_holds_back(tmp_path, monkeypatch):
    runner, ws = release_runner(tmp_path)
    seen = []
    monkeypatch.setattr(type(runner), "_session",
                        lambda self, prompt, **kw: seen.append(kw.get("extra_env")) or RoleOutcome("success", ""))
    with ws.hold("o", "r", STAGING):
        t = threading.Thread(target=lambda: runner.run(
            owner="o", repo="r", role="release", issue=3, model="m", github_token="t",
            workspace=STAGING, run_id="3", simulate=None))
        t.start()
        assert wait_for(lambda: ws.waiting("o", "r", STAGING) == 1)
    t.join(30)
    assert seen == [{}]
