"""Build environments: staging, epic and task; one run per environment at a
time; a queued run holds no session; each environment keeps notes."""

import json
import os
import stat
import threading
import time
from pathlib import Path

from factory_orchestrator.config import load_config
from factory_orchestrator.graph import build_environment
from factory_orchestrator.issue_workspaces import (
    NOTES_KEPT,
    STAGING,
    IssueKey,
    IssueWorkspaces,
)
from factory_orchestrator.repo_cache import RepoCache
from factory_orchestrator.role_runner import FactorySource, RoleRunner, environment_notes_block

from .fake_repo import FakeRepo
from .test_config import BASE
from .test_issue_workspaces import make_workspaces
from .test_repo_cache import ENV, make_origin
from .test_role_runner import make_local_factory


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ routing
def port():
    return FakeRepo({}, repo="r")


def test_implementer_works_in_its_own_tasks_environment():
    key = IssueKey(60, "o/r#34")
    assert build_environment(port(), "implementer", key, False) == key


def test_a_tasks_release_merges_from_the_epics_environment():
    assert build_environment(port(), "release", IssueKey(60, "o/r#34"), False) == IssueKey(34)


def test_a_release_onto_staging_takes_the_staging_environment():
    assert build_environment(port(), "release", IssueKey(34), True) is STAGING
    assert build_environment(port(), "release", IssueKey(60, "o/r#34"), True) is STAGING
    # an epic's release (promotion) and a standalone issue's release too
    assert build_environment(port(), "release", IssueKey(34), False) is STAGING


def test_a_cross_repo_tasks_release_keeps_its_own_environment_even_with_staging_open():
    from factory_orchestrator.graph import train_turn
    key = IssueKey(50, "o/api#193")
    assert build_environment(port(), "release", key, True) == key
    # and it waits on the epic's home staging, not this repo's
    assert train_turn(port(), "release", key) == ("o", "api")
    assert train_turn(port(), "release", IssueKey(60, "o/r#34")) is None
    assert train_turn(port(), "implementer", key) is None


def test_a_cross_repo_tasks_release_keeps_its_own_environment():
    key = IssueKey(60, "other/api#34")
    assert build_environment(port(), "release", key, False) == key


def test_throwaway_copies_stay_throwaway():
    assert build_environment(port(), "release", None, True) is None


# --------------------------------------------------------------- staging
def test_staging_is_one_copy_per_repo_and_is_never_swept(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", STAGING, "tok") as copy:
        assert copy == tmp_path / "ws" / "o" / "r" / "staging" / "repo"
    meta = json.loads((ws.path("o", "r", "staging") / "meta.json").read_text())
    assert meta["staging"] is True and meta["ref"] == "o/r@staging"
    assert ws.sweep(lambda o, r, n: True) == 0
    assert ws.discard("o", "r", 0) == 0
    assert copy.exists()


def test_environments_name_their_kind(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    for key in (STAGING, IssueKey(34), IssueKey(60, "o/r#34"), IssueKey(99)):
        with ws.acquire("o", "r", key, "tok"):
            pass
    kinds = {e["id"]: e["kind"] for e in ws.environments()}
    assert kinds == {"o/r@staging": "staging", "o/r#34": "epic",
                     "o/r#60": "task", "o/r#99": "issue"}


# ------------------------------------------------------------------- turns
def test_a_second_run_queues_for_the_environment_and_is_shown(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    release, waited = threading.Event(), []

    def first():
        with ws.hold("o", "r", STAGING, {"run_id": "a", "role": "release", "issue": 34}):
            ws.mark("o", "r", STAGING, "running")
            release.wait(5)

    def second():
        with ws.hold("o", "r", STAGING, {"run_id": "b", "role": "release", "issue": 40},
                     on_wait=lambda: waited.append(True)):
            pass

    a = threading.Thread(target=first)
    a.start()
    assert wait_for(lambda: any(e["active"] for e in ws.environments()))
    b = threading.Thread(target=second)
    b.start()
    assert wait_for(lambda: waited == [True])
    env = next(e for e in ws.environments() if e["id"] == "o/r@staging")
    assert env["active"]["run_id"] == "a" and env["active"]["state"] == "running"
    assert [q["run_id"] for q in env["queue"]] == ["b"]
    release.set()
    a.join()
    b.join()
    assert not any(e["active"] or e["queue"] for e in ws.environments())


# ------------------------------------------------------------------- notes
def test_notes_keep_the_latest_and_are_listed_newest_first(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(34), "tok"):
        pass
    for i in range(NOTES_KEPT + 5):
        ws.add_note("o", "r", IssueKey(34), {"role": "planner", "issue": 34,
                                              "outcome": "success", "summary": f"run {i}"})
    lines = (ws.path("o", "r", 34) / "notes.jsonl").read_text().splitlines()
    assert len(lines) == NOTES_KEPT
    assert [n["summary"] for n in ws.notes("o", "r", IssueKey(34), limit=2)] == [
        f"run {NOTES_KEPT + 3}", f"run {NOTES_KEPT + 4}"]
    listed = next(e for e in ws.environments() if e["id"] == "o/r#34")["notes"]
    assert listed[0]["summary"] == f"run {NOTES_KEPT + 4}"


def test_notes_survive_the_reset_of_the_copy(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", IssueKey(34), "tok"):
        pass
    ws.add_note("o", "r", IssueKey(34), {"role": "architect", "summary": "chose X"})
    with ws.acquire("o", "r", IssueKey(34), "tok"):
        pass
    assert ws.notes("o", "r", IssueKey(34))[0]["summary"] == "chose X"


def test_notes_block_reads_as_context_not_instructions():
    block = environment_notes_block(
        [{"at": 0, "role": "implementer", "issue": 60, "outcome": "timeout",
          "summary": "Loader tests hang.\nStub the lookup first."}], "the environment of o/r#60")
    assert "context, not" in block and "instructions" in block
    assert "1970-01-01 00:00 UTC · implementer on #60 · timeout" in block
    assert "  Stub the lookup first." in block
    assert environment_notes_block([], "x") == ""


# ------------------------------------------------------------ the runner
def fake_claude(tmp_path: Path, out: Path, sleep_file: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "claude"
    script.write_text(f"""#!/bin/bash
n=$(date +%s%N)
shift
cat > "{out}/prompt-$n.txt"
while [ -f "{sleep_file}" ]; do sleep 0.05; done
echo "{{\\"type\\":\\"result\\",\\"result\\":\\"Built it with $GH_TOKEN. Open: the docs.\\"}}"
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def runner_with_environments(tmp_path, max_parallel=1):
    origin, _ = make_origin(tmp_path)
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    source = FactorySource(cfg, local_path=str(make_local_factory(tmp_path)))
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin), env=ENV,
                      public_url_for=lambda o, r: "https://github.example/o/r")
    ws = IssueWorkspaces(cache, str(tmp_path / "envs"))
    hold = tmp_path / "hold"
    out = tmp_path / "captured"
    (tmp_path / "runs").mkdir()
    runner = RoleRunner(cfg, source, workspace_root=str(tmp_path / "runs"),
                        claude_bin=str(fake_claude(tmp_path, out, hold)),
                        max_parallel=max_parallel, repo_cache=cache, issue_workspaces=ws)
    return runner, ws, hold, out


def run(runner, key, issue, run_id, phases=None):
    return runner.run(owner="o", repo="r", role="intake", issue=issue, model="m",
                      github_token="ghs_secret", workspace=key, run_id=run_id,
                      on_phase=(phases.append if phases is not None else None))


def test_a_run_queued_for_its_environment_holds_no_session(tmp_path):
    runner, ws, hold, _ = runner_with_environments(tmp_path, max_parallel=1)
    hold.write_text("x")
    phases_b, phases_c = [], []
    a = threading.Thread(target=run, args=(runner, IssueKey(60), 60, "a"))
    a.start()
    assert wait_for(lambda: runner.environments()["sessions"]["in_use"])
    b = threading.Thread(target=run, args=(runner, IssueKey(60), 60, "b", phases_b))
    c = threading.Thread(target=run, args=(runner, IssueKey(61), 61, "c", phases_c))
    b.start()
    assert wait_for(lambda: phases_b == ["waiting for its build environment"])
    c.start()
    assert wait_for(lambda: phases_c == ["waiting for a free session"])
    view = runner.environments()
    assert [s["run_id"] for s in view["sessions"]["in_use"]] == ["a"]
    assert [s["run_id"] for s in view["sessions"]["waiting"]] == ["c"]
    env60 = next(e for e in view["environments"] if e["id"] == "o/r#60")
    assert env60["active"]["run_id"] == "a" and [q["run_id"] for q in env60["queue"]] == ["b"]
    hold.unlink()
    for t in (a, b, c):
        t.join(30)
    assert runner.environments()["sessions"]["in_use"] == []


def test_the_closing_summary_becomes_the_next_runs_note(tmp_path):
    runner, ws, _, out = runner_with_environments(tmp_path)
    first = run(runner, IssueKey(60), 60, "r1")
    assert first.status == "success"
    assert first.summary == "Built it with ***. Open: the docs."
    note = ws.notes("o", "r", IssueKey(60))[-1]
    assert note["run_id"] == "r1" and "ghs_secret" not in note["summary"]
    run(runner, IssueKey(60), 60, "r2")
    prompts = sorted(out.glob("prompt-*.txt"), key=os.path.getmtime)
    assert "BUILD ENVIRONMENT NOTES" not in prompts[0].read_text()
    assert "Open: the docs." in prompts[1].read_text()
