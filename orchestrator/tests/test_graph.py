"""End-to-end graph tests with a stubbed role runner against the fake repo."""

import json
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from factory_orchestrator.config import load_config
from factory_orchestrator.graph import Engine, Processor, build_graph
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.role_runner import RoleOutcome

from .fake_repo import FakeRepo
from .test_config import BASE

APPROVERS = {"release_scope": ["boss"], "spec": ["boss"],
             "design": ["boss"], "implementation": ["boss"]}


class ConfiguredRepo(FakeRepo):
    """FakeRepo with factory config files and an orchestrator claim."""

    files = {
        ".github/factory-orchestrator.json": json.dumps({"engine": "langgraph"}),
        ".github/factory-approvers.json": json.dumps(APPROVERS),
    }

    def get_file(self, path, ref=None):
        return self.files.get(path)


class FakeApp:
    def __init__(self, world):
        self.world = world

    def installation_token(self, owner, repo):
        return "ghs_test"

    def repo_client(self, owner, repo):
        return self.world


class ScriptedRunner:
    """Stands in for headless Claude Code: role behaviours as functions."""

    def __init__(self, world, behaviours):
        self.world = world
        self.behaviours = behaviours
        self.calls = []

    def run(self, *, owner, repo, role, issue, model, github_token, **_):
        self.calls.append({"role": role, "issue": issue, "model": model})
        behave = self.behaviours.get(role)
        if behave:
            behave(self.world, issue)
        return RoleOutcome(status="success", transcript=f"ran {role} on #{issue}", exit_code=0)


def make_engine(tmp_path, world, behaviours):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/l.db"})
    ledger = Ledger(cfg.database_url)
    runner = ScriptedRunner(world, behaviours)
    engine = Engine(cfg, ledger, FakeApp(world), runner, probe=lambda m: True,
                    transcript_dir=str(tmp_path / "tr"),
                    port_factory=lambda o, r: world)
    (tmp_path / "tr").mkdir(exist_ok=True)
    return engine, ledger, runner


def graph_with(tmp_path, world, behaviours):
    engine, ledger, runner = make_engine(tmp_path, world, behaviours)
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    return build_graph(engine, checkpointer=saver), engine, ledger, runner


def issue(n, title, labels, **kw):
    return {"number": n, "title": title, "labels": [{"name": x} for x in labels],
            "user": {"type": kw.get("user", "User")}, "state": "open",
            "milestone": kw.get("milestone")}


def flip(world, n, frm, to):
    world.remove_label(n, frm)
    world.add_labels(n, [to])
    world.create_comment(n, f"moved to {to}\n\n<!-- factory-agent -->")


def test_intake_run_moves_issue_and_checkpoints(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    graph, engine, ledger, runner = graph_with(
        tmp_path, world, {"intake": lambda w, n: flip(w, n, "factory:intake", "factory:spec-ready")})
    payload = {"action": "opened", "issue": world.issues[5],
               "repository": {"full_name": "o/r"}}
    cfgc = {"configurable": {"thread_id": "o/r#5"}}
    Processor(engine, graph)("issues", payload)
    assert "factory:spec-ready" in world.labels_of(5)
    assert "factory:in-progress" not in world.labels_of(5)
    assert [c["role"] for c in runner.calls] == ["intake"]
    runs = ledger.list_runs(repo="o/r", issue=5)
    assert len(runs) == 1 and runs[0]["outcome"] == "success"
    bodies = [c["body"] for c in world.comments.get(5, [])]
    assert any("is running" in b and f"/runs/{runs[0]['id']}" in b for b in bodies)
    state = graph.get_state(cfgc)
    assert state.values["completed"][0]["status"] == "success"


def test_claim_refusal_drops_event(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    world.files = {**ConfiguredRepo.files,
                   ".github/factory-orchestrator.json": json.dumps({"engine": "github-actions"})}
    graph, engine, ledger, runner = graph_with(tmp_path, world, {})
    Processor(engine, graph)("issues", {"action": "opened", "issue": world.issues[5],
                                        "repository": {"full_name": "o/r"}})
    assert runner.calls == []
    assert "factory:intake" not in world.labels_of(5)


def test_planner_chains_architect(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Epic", ["factory:spec-ready"])})
    graph, engine, ledger, runner = graph_with(tmp_path, world, {
        "planner": lambda w, n: flip(w, n, "factory:spec-approved", "factory:planned"),
        "architect": lambda w, n: flip(w, n, "factory:planned", "factory:design-ready"),
    })
    payload = {"action": "created", "issue": world.issues[5],
               "comment": {"body": "Approved", "user": {"login": "boss", "type": "User"},
                           "author_association": "OWNER"},
               "repository": {"full_name": "o/r"}}
    Processor(engine, graph)("issue_comment", payload)
    assert [c["role"] for c in runner.calls] == ["planner", "architect"]
    assert "factory:design-ready" in world.labels_of(5)


def test_planner_not_reaching_planned_does_not_chain(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Epic", ["factory:spec-ready"])})
    graph, engine, ledger, runner = graph_with(tmp_path, world, {
        # planner blocks instead of planning
        "planner": lambda w, n: (w.add_labels(n, ["factory:blocked"]),
                                 w.create_comment(n, "stuck\n\n<!-- factory-agent -->")),
    })
    payload = {"action": "created", "issue": world.issues[5],
               "comment": {"body": "Approved", "user": {"login": "boss", "type": "User"},
                           "author_association": "OWNER"},
               "repository": {"full_name": "o/r"}}
    Processor(engine, graph)("issue_comment", payload)
    assert [c["role"] for c in runner.calls] == ["planner"]


def test_g0_release_fans_out_intakes(tmp_path):
    ms = {"number": 7, "title": "v0.4", "html_url": "u"}
    world = ConfiguredRepo({
        1: issue(1, "release(7): v0.4", ["factory:release", "factory:release-ready"],
                 user="Bot", milestone=ms),
        5: issue(5, "A", ["factory:backlog"], milestone=ms),
        6: issue(6, "B", ["factory:backlog"], milestone=ms),
    })
    graph, engine, ledger, runner = graph_with(
        tmp_path, world, {"intake": lambda w, n: flip(w, n, "factory:intake", "factory:spec-ready")})
    payload = {"action": "created", "issue": world.issues[1],
               "comment": {"body": "Approved", "user": {"login": "boss", "type": "User"},
                           "author_association": "OWNER"},
               "repository": {"full_name": "o/r"}}
    Processor(engine, graph)("issue_comment", payload)
    assert sorted(c["issue"] for c in runner.calls) == [5, 6]
    assert all(c["role"] == "intake" for c in runner.calls)
    assert "factory:spec-ready" in world.labels_of(5)
    assert "factory:spec-ready" in world.labels_of(6)
    receipt = [c["body"] for c in world.comments[1]]
    assert any("factory-release-dispatched" in b for b in receipt)
    # a second identical event must not fan out twice (dispatch receipt)
    Processor(engine, graph)("issue_comment", payload)
    assert len(runner.calls) == 2


def test_silent_role_is_failed_and_reported(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    graph, engine, ledger, runner = graph_with(tmp_path, world, {})  # intake does nothing
    Processor(engine, graph)("issues", {"action": "opened", "issue": world.issues[5],
                                        "repository": {"full_name": "o/r"}})
    runs = ledger.list_runs(repo="o/r", issue=5)
    assert runs and runs[0]["outcome"] == "no_op"
    assert "changed nothing" in (runs[0]["error"] or "")
    bodies = [c["body"] for c in world.comments.get(5, [])]
    assert any("run failed" in b and f"/runs/{runs[0]['id']}" in b for b in bodies)
    assert any("changed nothing" in b for b in bodies)
    assert "factory:in-progress" not in world.labels_of(5)
    log = (tmp_path / "tr" / f"{runs[0]['id']}.log").read_text()
    assert log.startswith(runs[0]["error"])


def test_boots_identically_with_langsmith_env(tmp_path, monkeypatch):
    # LangSmith is env-only wiring: setting the variables must not change
    # behaviour when the endpoint is unreachable, and unsetting them is the
    # same code path.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    graph, engine, ledger, runner = graph_with(
        tmp_path, world, {"intake": lambda w, n: flip(w, n, "factory:intake", "factory:spec-ready")})
    Processor(engine, graph)("issues", {"action": "opened", "issue": world.issues[5],
                                        "repository": {"full_name": "o/r"}})
    assert [c["role"] for c in runner.calls] == ["intake"]


def test_model_exhaustion_fails_run(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    engine, ledger, runner = make_engine(tmp_path, world, {})
    engine.probe = lambda m: False
    graph = build_graph(engine)
    Processor(engine, graph)("issues", {"action": "opened", "issue": world.issues[5],
                                        "repository": {"full_name": "o/r"}})
    runs = ledger.list_runs(repo="o/r", issue=5)
    assert runs and runs[0]["outcome"] == "error"
    assert "preference chain" in runs[0]["error"]
    assert runner.calls == []
    assert "factory:in-progress" not in world.labels_of(5)


def test_role_fails_without_anthropic_credential(tmp_path):
    world = ConfiguredRepo({5: issue(5, "Add renewals", [])})
    cfg = load_config({**BASE, "ANTHROPIC_API_KEY": "",
                       "DATABASE_URL": f"sqlite:///{tmp_path}/l.db"})
    ledger = Ledger(cfg.database_url)
    runner = ScriptedRunner(world, {})
    engine = Engine(cfg, ledger, FakeApp(world), runner, probe=lambda m: True,
                    transcript_dir=str(tmp_path / "tr"),
                    port_factory=lambda o, r: world)
    (tmp_path / "tr").mkdir(exist_ok=True)
    Processor(engine, build_graph(engine))(
        "issues", {"action": "opened", "issue": world.issues[5],
                   "repository": {"full_name": "o/r"}})
    runs = ledger.list_runs(repo="o/r", issue=5)
    assert runs and runs[0]["outcome"] == "error"
    assert "No Anthropic credential" in (runs[0]["error"] or "")
    assert runner.calls == []
    assert "factory:in-progress" not in world.labels_of(5)
