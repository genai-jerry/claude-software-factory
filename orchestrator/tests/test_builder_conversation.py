"""A builder's Claude conversation is kept in its task's environment and
continued on its next run, instead of starting over and re-reading."""

import json
import stat
from pathlib import Path

from factory_orchestrator import issue_workspaces
from factory_orchestrator.config import load_config
from factory_orchestrator.issue_workspaces import IssueKey, IssueWorkspaces
from factory_orchestrator.repo_cache import RepoCache
from factory_orchestrator.role_runner import FactorySource, RoleOutcome, RoleRunner

from .test_config import BASE
from .test_repo_cache import ENV, make_origin
from .test_role_runner import make_local_factory

TASK = IssueKey(60, "o/r#34")


def fake_claude(tmp_path: Path, out: Path) -> Path:
    """Writes its conversation where Claude does, under $HOME/.claude/projects,
    and refuses a --resume whose conversation is not there."""
    out.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "claude"
    script.write_text(f"""#!/bin/bash
out="{out}"
n=$(date +%s%N)
args="$*"
cat > "$out/prompt-$n.txt"
echo "$args" > "$out/argv-$n.txt"
sid=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--resume" ]; then sid="$a"; fi
  prev="$a"
done
proj="$HOME/.claude/projects/-work-repo"
if [ -n "$sid" ]; then
  if [ -f "{tmp_path}/refuse-resume" ] || [ ! -f "$proj/$sid.jsonl" ]; then
    echo "No conversation found with session ID: $sid" >&2
    exit 1
  fi
else
  sid="s-$n"
fi
mkdir -p "$proj"
echo '{{"turn": "'$n'"}}' >> "$proj/$sid.jsonl"
echo '{{"type":"system","subtype":"init","session_id":"'$sid'"}}'
echo '{{"type":"assistant","message":{{"content":[{{"type":"text","text":"working"}}]}}}}'
echo '{{"type":"result","result":"Round done.","session_id":"'$sid'"}}'
if [ -f "{tmp_path}/fail" ]; then exit 1; fi
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def setup(tmp_path):
    origin, _ = make_origin(tmp_path)
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    factory = make_local_factory(tmp_path)
    for role in ("implementer", "reviewer"):
        (factory / "commands" / f"{role}.md").write_text(f"# {role}\n{role.upper()} RULES\n")
    source = FactorySource(cfg, local_path=str(factory))
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin), env=ENV,
                      public_url_for=lambda o, r: "https://github.example/o/r")
    ws = IssueWorkspaces(cache, str(tmp_path / "envs"))
    (tmp_path / "runs").mkdir()
    out = tmp_path / "captured"
    runner = RoleRunner(cfg, source, workspace_root=str(tmp_path / "runs"),
                        claude_bin=str(fake_claude(tmp_path, out)),
                        repo_cache=cache, issue_workspaces=ws)
    return runner, ws, out


def run(runner, role="implementer") -> RoleOutcome:
    return runner.run(owner="o", repo="r", role=role, issue=60, model="m",
                      github_token="ghs_secret", workspace=TASK, run_id="x")


def last(out: Path, kind: str) -> str:
    files = sorted(out.glob(f"{kind}-*.txt"))
    return files[-1].read_text()


def test_the_builders_next_run_continues_its_conversation(tmp_path):
    runner, ws, out = setup(tmp_path)
    first = run(runner)
    assert first.status == "success"
    assert first.conversation == {"resumed": False, "round": 1}
    assert "HANDBOOK BODY" in last(out, "prompt")
    sid = first.session_id

    second = run(runner)
    assert second.status == "success"
    assert second.conversation == {"resumed": True, "round": 2}
    assert f"--resume {sid}" in last(out, "argv")
    prompt = last(out, "prompt")
    # the new run's facts and the role rules, not the handbook again
    assert "this is round 2" in prompt and "IMPLEMENTER RULES" in prompt
    assert "HANDBOOK BODY" not in prompt
    assert "Round done." in prompt  # the environment's note from round 1
    assert second.session_id == sid

    third = run(runner)
    assert third.conversation == {"resumed": True, "round": 3}


def test_a_conversation_that_will_not_open_falls_back_to_a_fresh_run(tmp_path):
    runner, ws, out = setup(tmp_path)
    run(runner)
    (tmp_path / "refuse-resume").write_text("x")
    again = run(runner)
    assert again.status == "success"
    assert again.conversation == {"resumed": False, "round": 1}
    assert "HANDBOOK BODY" in last(out, "prompt")


def test_a_run_that_ends_in_an_error_is_not_continued(tmp_path):
    runner, ws, out = setup(tmp_path)
    run(runner)
    (tmp_path / "fail").write_text("x")
    assert run(runner).status == "error"
    (tmp_path / "fail").unlink()
    fresh = run(runner)
    assert fresh.conversation == {"resumed": False, "round": 1}
    assert "--resume" not in last(out, "argv")


def test_a_long_conversation_starts_over(tmp_path, monkeypatch):
    monkeypatch.setattr(issue_workspaces, "CONVERSATION_MAX_ROUNDS", 2)
    runner, ws, out = setup(tmp_path)
    run(runner)
    assert run(runner).conversation == {"resumed": True, "round": 2}
    assert run(runner).conversation == {"resumed": False, "round": 1}


def test_other_roles_start_fresh_every_time(tmp_path):
    runner, ws, out = setup(tmp_path)
    run(runner, "reviewer")
    second = run(runner, "reviewer")
    assert second.conversation is None
    assert "--resume" not in last(out, "argv")
    assert not (ws.home("o", "r", TASK) / "conversations").exists()


def test_the_kept_conversation_lives_beside_the_copy_not_in_it(tmp_path):
    runner, ws, out = setup(tmp_path)
    first = run(runner)
    kept = ws.home("o", "r", TASK) / "conversations" / "implementer-60"
    meta = json.loads((kept / "conversation.json").read_text())
    assert meta["session_id"] == first.session_id and meta["rounds"] == 1
    assert (kept / meta["path"]).is_file()
    assert not (ws.home("o", "r", TASK) / "repo" / ".claude").exists()


def test_a_kept_path_that_escapes_is_refused(tmp_path):
    runner, ws, out = setup(tmp_path)
    run(runner)
    kept = ws.home("o", "r", TASK) / "conversations" / "implementer-60"
    meta = json.loads((kept / "conversation.json").read_text())
    (kept / "conversation.json").write_text(json.dumps({**meta, "path": "../../evil.jsonl"}))
    assert run(runner).conversation == {"resumed": False, "round": 1}
