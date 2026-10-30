"""Issue workspaces: one copy per issue, reset to GitHub at the start of every run."""

import json
import threading

from factory_orchestrator.graph import Processor
from factory_orchestrator.issue_workspaces import IssueKey, IssueWorkspaces, workspace_key
from factory_orchestrator.main import sweep_workspaces
from factory_orchestrator.repo_cache import RepoCache

from .fake_repo import FakeRepo
from .test_graph import ConfiguredRepo, ScriptedRunner, graph_with, issue
from .test_repo_cache import ENV, commit, git, make_origin

PUBLIC = "https://github.example/o/r"


def make_workspaces(tmp_path, origin, *, clock=None, idle_days=7.0):
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin), env=ENV,
                      public_url_for=lambda o, r: PUBLIC)
    kw = {"clock": clock} if clock else {}
    return IssueWorkspaces(cache, str(tmp_path / "ws"), idle_days=idle_days, **kw)


def ignore_node_modules(work):
    (work / ".gitignore").write_text("node_modules/\n")
    commit(work, ".gitignore", "node_modules/\n")


# ------------------------------------------------------------ key resolution
def test_epic_or_standalone_issue_is_its_own_key():
    world = FakeRepo({34: issue(34, "Store booker status", [])})
    assert workspace_key(world, 34) == IssueKey(34)


def test_task_records_its_epic_in_the_same_repo():
    world = FakeRepo({60: {**issue(60, "task(34): DB column", []), "body": "Part of #34"}})
    assert workspace_key(world, 60) == IssueKey(60, "o/r#34")


def test_cross_repo_task_records_the_epic_repo():
    world = FakeRepo({60: {**issue(60, "task(34): web form", []),
                           "body": "Part of genai-jerry/beacon-api#34"}}, repo="beacon-web")
    assert workspace_key(world, 60) == IssueKey(60, "genai-jerry/beacon-api#34")


def test_pr_resolves_to_the_task_it_closes():
    world = FakeRepo({
        60: {**issue(60, "task(34): DB column", []), "body": "Part of #34"},
        70: {**issue(70, "DB column", []), "pull_request": {}, "body": "Closes #60\n\n..."},
    })
    assert workspace_key(world, 70) == IssueKey(60, "o/r#34")


def test_pr_that_closes_nothing_keeps_its_own_number():
    world = FakeRepo({70: {**issue(70, "chore", []), "pull_request": {}, "body": "tidy"}})
    assert workspace_key(world, 70) == IssueKey(70)


# --------------------------------------------------------- reuse and reset
def test_ignored_files_survive_between_runs_on_one_issue(tmp_path):
    origin, work = make_origin(tmp_path)
    ignore_node_modules(work)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        (copy / "node_modules").mkdir()
        (copy / "node_modules" / "dep.js").write_text("warm")
    with ws.acquire("o", "r", IssueKey(60), "tok") as again:
        assert again == copy
        assert (again / "node_modules" / "dep.js").read_text() == "warm"


def test_each_issue_gets_its_own_copy(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60, "o/r#34"), "tok") as a, \
            ws.acquire("o", "r", IssueKey(61, "o/r#34"), "tok") as b:
        assert a != b
        assert a == tmp_path / "ws" / "o" / "r" / "60" / "repo"


def test_a_run_starts_from_what_is_on_github(tmp_path):
    origin, work = make_origin(tmp_path)
    git("push", "-q", "origin", "HEAD:refs/heads/factory/60-col", cwd=work)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        git("checkout", "-q", "factory/60-col", cwd=copy)
        (copy / "README.md").write_text("uncommitted edit")
        (copy / "scratch.txt").write_text("untracked")
        (copy / "unpushed.txt").write_text("u")
        git("add", "unpushed.txt", cwd=copy)
        git("commit", "-qm", "never pushed", cwd=copy)
        git("checkout", "-q", "-b", "factory/local-only", cwd=copy)
        (copy / "stashed.txt").write_text("s")
        git("add", "stashed.txt", cwd=copy)
        git("stash", cwd=copy)
        (copy / ".git" / "index.lock").write_text("")

    # Meanwhile a human pushes to main and force-pushes the task branch.
    commit(work, "HUMAN.md")
    git("checkout", "-q", "-b", "rewritten", "HEAD~1", cwd=work)
    commit_on = work / "REWRITE.md"
    commit_on.write_text("r")
    git("add", ".", cwd=work)
    git("commit", "-qm", "rewrite", cwd=work)
    git("push", "-q", "-f", "origin", "HEAD:refs/heads/factory/60-col", cwd=work)

    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=copy) == "main"
        assert (copy / "HUMAN.md").exists()
        assert git("status", "--porcelain", cwd=copy) == ""
        assert not (copy / "scratch.txt").exists()
        assert git("stash", "list", cwd=copy) == ""
        assert "factory/local-only" not in git("branch", cwd=copy)
        assert git("rev-parse", "factory/60-col", cwd=copy) == \
            git("rev-parse", "refs/heads/factory/60-col", cwd=origin)
        git("checkout", "-q", "factory/60-col", cwd=copy)
        assert (copy / "REWRITE.md").exists() and not (copy / "unpushed.txt").exists()


def test_token_is_on_origin_only_while_the_run_is_live(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        assert git("remote", "get-url", "origin", cwd=copy) == str(origin)
    assert git("remote", "get-url", "origin", cwd=copy) == PUBLIC


def test_a_copy_that_cannot_be_reset_is_copied_afresh(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        pass
    (copy / ".git" / "HEAD").write_text("garbage")
    with ws.acquire("o", "r", IssueKey(60), "tok") as copy:
        assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=copy) == "main"
        assert (copy / "README.md").read_text() == "hello"


def test_runs_on_one_issue_take_turns(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    inside, overlap = threading.Lock(), []

    def one():
        with ws.acquire("o", "r", IssueKey(60), "tok"):
            if not inside.acquire(blocking=False):
                overlap.append(True)
                return
            threading.Event().wait(0.2)
            inside.release()

    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap == []


def test_meta_records_the_epic(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60, "o/r#34"), "tok"):
        pass
    meta = json.loads((ws.path("o", "r", 60) / "meta.json").read_text())
    assert meta["ref"] == "o/r#60" and meta["epic"] == "o/r#34"


# ------------------------------------------------------------------ cleanup
def make_three(tmp_path, ws):
    for key in (IssueKey(34), IssueKey(60, "o/r#34"), IssueKey(99)):
        with ws.acquire("o", "r", key, "tok"):
            pass


def test_closing_a_task_discards_only_its_copy(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    make_three(tmp_path, ws)
    assert ws.discard("o", "r", 60) == 1
    assert not ws.path("o", "r", 60).exists()
    assert ws.path("o", "r", 34).exists() and ws.path("o", "r", 99).exists()


def test_closing_an_epic_discards_its_tasks_copies(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    make_three(tmp_path, ws)
    assert ws.discard("o", "r", 34) == 2
    assert not ws.path("o", "r", 34).exists() and not ws.path("o", "r", 60).exists()
    assert ws.path("o", "r", 99).exists()


def test_a_copy_in_use_is_not_discarded(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok"):
        assert ws.discard("o", "r", 60) == 0
        assert ws.sweep(lambda o, r, n: True) == 0
    assert ws.path("o", "r", 60).exists()


def test_sweep_removes_closed_and_idle_copies(tmp_path):
    origin, _ = make_origin(tmp_path)
    now = [1_000_000.0]
    ws = make_workspaces(tmp_path, origin, clock=lambda: now[0], idle_days=7)
    make_three(tmp_path, ws)
    with ws.acquire("o", "r", IssueKey(61), "tok"):
        pass
    now[0] += 8 * 86400                       # all four idle for 8 days...
    with ws.acquire("o", "r", IssueKey(99), "tok"):
        pass                                  # ...except #99, used just now

    closed = {34}
    removed = ws.sweep(lambda o, r, n: n in closed)
    assert removed == 3                       # #34 closed; #60, #61 idle
    assert ws.path("o", "r", 99).exists()


def test_sweep_keeps_a_copy_whose_issue_cannot_be_read(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(60), "tok"):
        pass

    def boom(o, r, n):
        raise RuntimeError("GitHub is down")

    assert ws.sweep(boom) == 0
    assert ws.path("o", "r", 60).exists()


# ------------------------------------------------------------ engine wiring
class RecordingRunner(ScriptedRunner):
    def __init__(self, world, behaviours, workspaces=None):
        super().__init__(world, behaviours)
        self.issue_workspaces = workspaces
        self.workspaces = []

    def run(self, **kw):
        self.workspaces.append(kw.get("workspace"))
        return super().run(**kw)


def engine_for(tmp_path, world, runner_settings, workspaces=None):
    world.files = {**ConfiguredRepo.files, ".github/factory-orchestrator.json":
                   json.dumps({"engine": "langgraph", "runners": runner_settings})}
    graph, engine, ledger, _ = graph_with(tmp_path, world, {})
    engine.runner = RecordingRunner(world, {}, workspaces)
    return graph, engine


def test_repo_on_issue_workspaces_runs_in_the_tasks_copy(tmp_path):
    world = ConfiguredRepo({
        60: {**issue(60, "task(34): DB column", []), "body": "Part of #34"},
        70: {**issue(70, "DB column", ["factory:in-review"]), "pull_request": {},
             "body": "Closes #60"},
    })
    graph, engine = engine_for(tmp_path, world, {"workspace": "issue"})
    from factory_orchestrator.graph import execute_role
    execute_role(engine, {"owner": "o", "repo": "r", "role": "reviewer", "issue": 70})
    assert engine.runner.workspaces == [IssueKey(60, "o/r#34")]


def test_repo_without_the_setting_keeps_a_copy_per_run(tmp_path):
    world = ConfiguredRepo({60: issue(60, "task(34): DB column", [])})
    graph, engine = engine_for(tmp_path, world, {"max_parallel": 2})
    from factory_orchestrator.graph import execute_role
    execute_role(engine, {"owner": "o", "repo": "r", "role": "implementer", "issue": 60})
    assert engine.runner.workspaces == [None]


def test_closed_issue_event_discards_its_copies(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    make_three(tmp_path, ws)
    world = ConfiguredRepo({34: {**issue(34, "Epic", []), "state": "closed"}})
    graph, engine = engine_for(tmp_path, world, {"workspace": "issue"}, ws)
    Processor(engine, graph)("issues", {"action": "closed", "issue": world.issues[34],
                                        "repository": {"full_name": "o/r"}})
    assert not ws.path("o", "r", 34).exists() and not ws.path("o", "r", 60).exists()
    assert ws.path("o", "r", 99).exists()


def test_reconciler_sweep_asks_github_whether_each_issue_closed(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    make_three(tmp_path, ws)
    world = ConfiguredRepo({34: {**issue(34, "Epic", []), "state": "open"},
                            60: {**issue(60, "task(34)", []), "state": "closed"}})
    graph, engine = engine_for(tmp_path, world, {"workspace": "issue"}, ws)
    # #99 is not on GitHub at all (deleted) - treated as closed.
    assert sweep_workspaces(engine) == 2
    assert ws.path("o", "r", 34).exists()
