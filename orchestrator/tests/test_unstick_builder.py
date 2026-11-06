"""A task too big for one run: its unfinished work is kept between runs,
running out of turns is said as such, the sweep says when it stops
retrying, and a PR the engine opens goes to the epic branch.

beacon-api#202 (5–6 Nov 2026) ran nine times, every one stopped at the turn
limit or the clock with the suite red, nothing pushed — and each next run
started from nothing because the copy is reset to GitHub."""

import datetime as dt
import json
import stat
import subprocess
from pathlib import Path

from factory_orchestrator.claude_stream import StreamReader
from factory_orchestrator.config import load_config
from factory_orchestrator.graph import pr_base_for
from factory_orchestrator.issue_workspaces import IssueKey, IssueWorkspaces
from factory_orchestrator.reconcile import gave_up_on, report_gave_up, sweep_repo
from factory_orchestrator.repo_cache import RepoCache
from factory_orchestrator.role_runner import FactorySource, RoleRunner, hit_turn_limit

from .test_config import BASE
from .test_graph import ConfiguredRepo, issue, make_engine
from .test_issue_workspaces import make_workspaces
from .test_reconcile import make_ledger
from .test_repo_cache import ENV, commit, git, make_origin
from .test_role_runner import make_local_factory

TASK = IssueKey(60, "o/r#34")


def g(copy, *args):
    return subprocess.run(["git", "-C", str(copy), *args], check=True, capture_output=True,
                          text=True, env=ENV).stdout.strip()


# ----------------------------------------------------------- kept work
def test_unpushed_commits_and_edits_come_back_after_the_reset(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", TASK, "tok") as copy:
        g(copy, "checkout", "-q", "-b", "factory/60-promoted-default")
        (copy / "a.py").write_text("committed")
        g(copy, "add", "a.py")
        g(copy, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "half")
        (copy / "b.py").write_text("edited, not committed")
        meta = ws.save_wip("o", "r", TASK, copy, "run-1")
    assert meta and meta["branch"] == "factory/60-promoted-default"
    assert meta["commits"] == 1 and meta["uncommitted"] is True

    with ws.acquire("o", "r", TASK, "tok") as copy:
        assert not (copy / "b.py").exists()  # the reset dropped it...
        back = ws.restore_wip("o", "r", TASK, copy)
        assert back and back["run_id"] == "run-1"
        assert g(copy, "rev-parse", "--abbrev-ref", "HEAD") == "factory/60-promoted-default"
        assert (copy / "a.py").read_text() == "committed"
        assert (copy / "b.py").read_text() == "edited, not committed"  # ...and it is back
        assert g(copy, "log", "-1", "--pretty=%s") == "half"  # the carrier commit is undone
        assert "b.py" in g(copy, "status", "--porcelain")


def test_nothing_on_a_task_branch_keeps_nothing(tmp_path):
    origin, _ = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", TASK, "tok") as copy:
        assert ws.save_wip("o", "r", TASK, copy) is None  # on main, clean
        g(copy, "checkout", "-q", "-b", "factory/epic-34")
        (copy / "x.py").write_text("x")
        assert ws.save_wip("o", "r", TASK, copy) is None  # never the epic branch
    assert not (ws.home("o", "r", TASK) / "wip").exists()


def test_github_moving_the_branch_on_wins_over_the_kept_work(tmp_path):
    origin, work = make_origin(tmp_path)
    ws = make_workspaces(tmp_path, origin)
    with ws.acquire("o", "r", TASK, "tok") as copy:
        g(copy, "checkout", "-q", "-b", "factory/60-x")
        (copy / "mine.py").write_text("mine")
        ws.save_wip("o", "r", TASK, copy)
    git("checkout", "-q", "-b", "factory/60-x", cwd=work)
    commit(work, "theirs.py", "pushed by someone else")
    with ws.acquire("o", "r", TASK, "tok") as copy:
        assert ws.restore_wip("o", "r", TASK, copy) is None
        assert not (copy / "mine.py").exists()
    assert not (ws.home("o", "r", TASK) / "wip").exists()


# --------------------------------------------------------- out of turns
def test_the_turn_limit_reads_as_running_out_not_a_crash():
    r = StreamReader()
    r.feed(json.dumps({"type": "result", "subtype": "error_max_turns", "num_turns": 101}))
    assert hit_turn_limit(r, 100)
    r2 = StreamReader()
    r2.feed(json.dumps({"type": "result", "subtype": "success", "num_turns": 101}))
    assert hit_turn_limit(r2, 100)  # older CLIs say it only by the count
    r3 = StreamReader()
    r3.feed(json.dumps({"type": "result", "subtype": "error_during_execution", "num_turns": 12}))
    assert not hit_turn_limit(r3, 100)


def fake_claude(tmp_path: Path, out: Path) -> Path:
    """Run 1 edits on its task branch and stops at the turn limit; run 2
    reports what it found in the copy."""
    out.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "claude"
    script.write_text(f"""#!/bin/bash
out="{out}"
n=$(date +%s%N)
cat > "$out/prompt-$n.txt"
echo "$*" > "$out/argv-$n.txt"
sid=""; prev=""
for a in "$@"; do if [ "$prev" = "--resume" ]; then sid="$a"; fi; prev="$a"; done
proj="$HOME/.claude/projects/-copy"
mkdir -p "$proj"
[ -z "$sid" ] && sid="s-$n"
echo '{{}}' >> "$proj/$sid.jsonl"
echo '{{"type":"system","subtype":"init","session_id":"'$sid'"}}'
echo '{{"type":"assistant","message":{{"content":[{{"type":"text","text":"working"}}]}}}}'
if [ ! -f "{tmp_path}/ran-once" ]; then
  touch "{tmp_path}/ran-once"
  git checkout -q -b factory/60-promoted-default
  echo "half done" > promoted.py
  echo '{{"type":"result","subtype":"error_max_turns","num_turns":101,"session_id":"'$sid'"}}'
  exit 1
fi
git rev-parse --abbrev-ref HEAD > "$out/branch.txt"
cat promoted.py > "$out/found.txt" 2>/dev/null
echo '{{"type":"result","subtype":"success","num_turns":20,"result":"Finished.","session_id":"'$sid'"}}'
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_a_run_that_ran_out_of_turns_hands_its_work_to_the_next(tmp_path):
    origin, _ = make_origin(tmp_path)
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    factory = make_local_factory(tmp_path)
    (factory / "commands" / "implementer.md").write_text("# implementer\nRULES\n")
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin), env=ENV,
                      public_url_for=lambda o, r: "https://github.example/o/r")
    ws = IssueWorkspaces(cache, str(tmp_path / "envs"))
    (tmp_path / "runs").mkdir()
    out = tmp_path / "captured"
    runner = RoleRunner(cfg, FactorySource(cfg, local_path=str(factory)),
                        workspace_root=str(tmp_path / "runs"),
                        claude_bin=str(fake_claude(tmp_path, out)), repo_cache=cache,
                        issue_workspaces=ws)

    def run():
        return runner.run(owner="o", repo="r", role="implementer", issue=60, model="m",
                          github_token="t", workspace=TASK, run_id="r")

    first = run()
    assert first.status == "error" and first.out_of_turns
    assert first.error.startswith("Ran out of turns: Claude used all 100 turns")
    assert "unfinished work and its conversation are kept" in first.error

    second = run()
    assert second.status == "success"
    assert second.conversation == {"resumed": True, "round": 2, "restored_work": True}
    assert (out / "branch.txt").read_text().strip() == "factory/60-promoted-default"
    assert (out / "found.txt").read_text().strip() == "half done"
    prompt = sorted(out.glob("prompt-*.txt"))[-1].read_text()
    assert "UNFINISHED WORK RESTORED" in prompt and "factory/60-promoted-default" in prompt
    # pushed or not, a successful run leaves no stale work behind
    assert not (ws.home("o", "r", TASK) / "wip").exists()


# -------------------------------------------------------------- PR base
class EpicRepo(ConfiguredRepo):
    files = {**ConfiguredRepo.files,
             ".github/factory-branches.json": json.dumps({"epics": True, "staging": "staging"})}


def test_a_pr_the_engine_opens_on_a_task_goes_to_its_epic_branch(tmp_path):
    w = EpicRepo({34: issue(34, "Epic", []), 60: issue(60, "task(34): The promoted default", [])})
    engine, _, _ = make_engine(tmp_path, w, {})
    assert pr_base_for(engine, w, 60) is None  # no epic branch yet: the default
    w.branches.append("factory/epic-34")
    assert pr_base_for(engine, w, 60) == "factory/epic-34"
    assert pr_base_for(engine, w, 34) is None  # an epic itself: not a task


def test_a_repo_without_epic_branches_keeps_the_default_base(tmp_path):
    w = ConfiguredRepo({60: issue(60, "task(34): x", [])})
    w.branches.append("factory/epic-34")
    engine, _, _ = make_engine(tmp_path, w, {})
    assert pr_base_for(engine, w, 60) is None


# ------------------------------------------------------- giving up, said
NOW = dt.datetime.now(dt.UTC)
OUT = "Ran out of turns: Claude used all 100 turns before it finished."


def fail(rid, mins, error=OUT, outcome="error"):
    return {"id": rid, "role": "implementer", "outcome": outcome, "error": error,
            "finished_at": NOW - dt.timedelta(minutes=mins)}


def test_after_its_retries_the_sweep_says_it_stopped_and_asks():
    w = ConfiguredRepo({60: issue(60, "task(34): The promoted default", ["factory:ready"])})
    runs = [fail("c", 20), fail("b", 60, "Role 'implementer' exceeded the 2700s wall clock.",
                                "timeout"), fail("a", 90)]
    assert gave_up_on(w.labels_of(60), runs) == "implementer"
    assert gave_up_on(w.labels_of(60), runs[:2]) is None  # still retrying
    assert report_gave_up(w, 60, "implementer", runs) == 1
    [body] = [c["body"] for c in w.comments[60]]
    assert "stopped retrying the Implementer" in body
    assert "ran out of turns (2×), ran out of time" in body
    assert "**Questions for you:**" in body and "too big for one run" in body
    assert "factory:blocked" in w.labels_of(60)
    assert not any(ch.isdigit() and f"#{ch}" in body for ch in "0123456789")
    # once per failed run, and not while it waits on a person
    assert report_gave_up(w, 60, "implementer", runs) == 0
    assert gave_up_on(w.labels_of(60), runs) is None


def test_the_sweep_posts_the_notice_once(tmp_path):
    w = ConfiguredRepo({60: issue(60, "task(34): The promoted default", ["factory:ready"])})
    ledger = make_ledger(tmp_path)
    for _ in range(3):
        ledger.finish_run(ledger.start_run(repo="o/r", issue=60, role="implementer", trigger="t"),
                          outcome="error", error=OUT)
    sweep_repo(w, ledger)
    sweep_repo(w, ledger)
    assert len([c for c in w.comments.get(60, []) if "stopped retrying" in c["body"]]) == 1
    assert ledger.claim_pending() == []  # and no fourth run was queued
