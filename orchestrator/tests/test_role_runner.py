import json
import os
import stat
import subprocess
from pathlib import Path

import yaml

from factory_orchestrator.config import load_config
from factory_orchestrator.role_runner import (
    ALLOWED_TOOLS,
    PROMPT_BODY,
    FactorySource,
    RoleRunner,
    assemble_prompt,
    inspect_pushable_branch,
    load_test_command,
)

from .test_config import BASE

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_local_factory(tmp_path: Path) -> Path:
    src = tmp_path / "factory"
    (src / "commands").mkdir(parents=True)
    (src / "FACTORY.md").write_text("# The Software Factory\nHANDBOOK BODY\n")
    (src / "commands" / "intake.md").write_text("# Intake\nROLE BODY\n")
    (src / "commands" / "fasttrack.md").write_text("# Fasttrack\nFASTTRACK BODY\n")
    return src


FACTORY_COMMIT_HOOK = """\
if [ ! -f .factory-committed ]; then
  git config user.email "factory@test"
  git config user.name "factory"
  git checkout -b factory/5-x
  echo change > observed.txt
  git add observed.txt
  git commit -qm "feat: observed change"
  touch .factory-committed
fi
"""


def make_fake_claude(tmp_path: Path, out_dir: Path, *, exit_code: int = 0,
                     sleep: float = 0, on_run: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    hook_line = ""
    if on_run:
        hook = tmp_path / "claude-hook.sh"
        hook.write_text(on_run)
        hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
        hook_line = f'bash "{hook}"'
    script = tmp_path / "claude"
    script.write_text(f"""#!/bin/bash
# fake claude: record prompt, argv, cwd, env for assertions
out="{out_dir}"
n=$(date +%s%N)
shift  # -p
printf '%s' "$1" > "$out/prompt-$n.txt"
shift
printf '%s\\n' "$@" > "$out/argv-$n.txt"
pwd > "$out/cwd-$n.txt"
echo "GH_TOKEN=$GH_TOKEN" > "$out/env-$n.txt"
{hook_line}
sleep {sleep}
echo "fake transcript with $GH_TOKEN inside"
exit {exit_code}
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def make_consuming_repo(tmp_path: Path, *, profile=None, extra_files=None) -> Path:
    repo = tmp_path / "origin" / "r"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("hello")
    if profile is not None:
        (repo / ".factory").mkdir(parents=True, exist_ok=True)
        (repo / ".factory" / "profile.json").write_text(json.dumps(profile))
    if extra_files:
        for rel, content in extra_files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    init = subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env,
                          capture_output=True)
    if init.returncode != 0:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env, capture_output=True)
    for cmd in (["git", "add", "."], ["git", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env, capture_output=True)
    return repo


def make_bare_origin(work: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "--bare", "-q", str(work), str(dest)],
                   check=True, capture_output=True,
                   env={"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    return dest


def install_fake_gh(tmp_path: Path, monkeypatch, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "gh"
    script.write_text(f"""#!/bin/bash
log="{out_dir}/gh.log"
{{
  printf 'gh'
  for a in "$@"; do printf ' %q' "$a"; done
  printf '\\n'
}} >> "$log"
if [ "$1" = pr ] && [ "$2" = list ]; then
  echo '[]'
  exit 0
fi
if [ "$1" = pr ] && [ "$2" = create ]; then
  echo 'https://github.com/o/r/pull/42'
  exit 0
fi
if [ "$1" = api ]; then
  echo '[]'
  exit 0
fi
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


def git_branches(repo: Path) -> set[str]:
    out = subprocess.check_output(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo, text=True)
    return {line.strip() for line in out.splitlines() if line.strip()}


def captured_prompts(out_dir: Path) -> list[str]:
    return [p.read_text() for p in sorted(out_dir.glob("prompt-*.txt"))]


PROFILE = {
    "repo": "r",
    "stack": "x",
    "branches": {"default": "main"},
    "commands": {"test": "echo ok"},
}


class LocalCloneRunner(RoleRunner):
    """Clone from the local fixture repo instead of github.com."""

    def __init__(self, *a, origin: Path, **kw):
        super().__init__(*a, **kw)
        self.origin = origin

    def clone_workspace(self, owner, repo, token, dest):
        subprocess.run(["git", "clone", "-q", f"file://{self.origin}", str(dest / repo)],
                       check=True, capture_output=True,
                       env={"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0"})


def build_runner(tmp_path, *, exit_code=0):
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    source = FactorySource(cfg, local_path=str(make_local_factory(tmp_path)))
    out_dir = tmp_path / "captured"
    claude = make_fake_claude(tmp_path, out_dir, exit_code=exit_code)
    runner = LocalCloneRunner(cfg, source, workspace_root=str(tmp_path / "ws"),
                              claude_bin=str(claude),
                              origin=make_consuming_repo(tmp_path))
    (tmp_path / "ws").mkdir(exist_ok=True)
    return cfg, runner, out_dir


def test_role_run_captures_prompt_and_cleans_workspace(tmp_path):
    cfg, runner, out = build_runner(tmp_path)
    outcome = runner.run(owner="o", repo="r", role="intake", issue=5,
                         model="claude-sonnet-5", github_token="ghs_secret_token")
    assert outcome.status == "success"
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert 'the "intake" role' in prompt
    assert "HANDBOOK BODY" in prompt
    assert "===== ROLE INSTRUCTIONS (intake) =====" in prompt
    assert "ROLE BODY" in prompt
    argv = next(out.glob("argv-*.txt")).read_text()
    assert "--permission-mode\nacceptEdits" in argv
    assert ALLOWED_TOOLS in argv
    assert "--max-turns\n100" in argv
    assert "--verbose" in argv
    # ran inside its own clone of the consuming repo...
    cwd = Path(next(out.glob("cwd-*.txt")).read_text().strip())
    assert cwd.name == "r" and str(cwd).startswith(str(tmp_path / "ws"))
    # ...which is deleted afterwards
    assert not cwd.exists()
    # token reached the agent env but is redacted from the transcript
    assert "GH_TOKEN=ghs_secret_token" in next(out.glob("env-*.txt")).read_text()
    assert "ghs_secret_token" not in outcome.transcript
    assert "***" in outcome.transcript


def test_workspaces_are_isolated_per_run(tmp_path):
    cfg, runner, out = build_runner(tmp_path)
    runner.run(owner="o", repo="r", role="intake", issue=5,
               model="m", github_token="t1")
    runner.run(owner="o", repo="r", role="intake", issue=6,
               model="m", github_token="t2")
    cwds = {p.read_text().strip() for p in out.glob("cwd-*.txt")}
    assert len(cwds) == 2  # never the same checkout


def test_nonzero_exit_is_error(tmp_path):
    cfg, runner, out = build_runner(tmp_path, exit_code=3)
    outcome = runner.run(owner="o", repo="r", role="intake", issue=5,
                         model="m", github_token="t")
    assert outcome.status == "error" and outcome.exit_code == 3


def test_prompt_body_matches_actions_engine():
    """The shared middle of the prompt is byte-identical to the workflow's own
    heredoc — same handbook framing, same operating rules, same cross-repo
    instructions. Only the engine-identity sentence and the triggering note
    are engine-specific."""
    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "factory-pipeline.yml")
                        .read_text())
    step = next(s for s in wf["jobs"]["agent"]["steps"]
                if s.get("name") == "Run factory role (push)")
    script = step["run"]
    lines = script.splitlines()
    start = next(i for i, l in enumerate(lines) if "cat <<PROMPT" in l) + 1
    end = next(i for i, l in enumerate(lines) if l.strip() == "PROMPT" and i > start)
    heredoc = "\n".join(lines[start:end])
    # undo shell heredoc escaping and substitute the env vars the step fills in
    heredoc = (heredoc.replace("\\`", "`").replace("\\$", "$")
               .replace("${GITHUB_REPOSITORY_OWNER}", "o")
               .replace("$GITHUB_REPOSITORY", "o/r")
               .replace("$ROLE", "intake").replace("$ISSUE", "5"))
    shared_actions = heredoc[heredoc.index("The factory handbook"):
                             heredoc.index("Note on triggering")]
    ours = assemble_prompt(role="intake", repository="o/r", owner="o", issue=5,
                           handbook="H", role_instructions="R")
    shared_ours = ours[ours.index("The factory handbook"):ours.index("Note on triggering")]
    assert shared_ours == shared_actions
    # and PROMPT_BODY is exactly that shared block
    assert PROMPT_BODY.format(issue=5, owner="o") == shared_actions
    assert "one-shot session" in ours
    assert "Never background test, build, or lint" in ours


def _observer_profile(test_command):
    profile = dict(PROFILE)
    profile["commands"] = {"test": test_command}
    return profile


def build_observer_runner(tmp_path, monkeypatch, *, test_command="echo ok",
                          commit_factory_branch=True, on_run=None, exit_code=0):
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    source = FactorySource(cfg, local_path=str(make_local_factory(tmp_path)))
    out_dir = tmp_path / "captured"
    if on_run is None and commit_factory_branch:
        on_run = FACTORY_COMMIT_HOOK
    claude = make_fake_claude(tmp_path, out_dir, exit_code=exit_code, on_run=on_run)
    work = make_consuming_repo(tmp_path, profile=_observer_profile(test_command))
    origin = make_bare_origin(work, tmp_path / "origin.git")
    install_fake_gh(tmp_path, monkeypatch, out_dir)
    runner = LocalCloneRunner(cfg, source, workspace_root=str(tmp_path / "ws"),
                              claude_bin=str(claude), origin=origin)
    (tmp_path / "ws").mkdir(exist_ok=True)
    return cfg, runner, out_dir, origin


def test_observer_push_on_green(tmp_path, monkeypatch):
    cfg, runner, out, origin = build_observer_runner(tmp_path, monkeypatch)
    phases = []
    outcome = runner.run(owner="o", repo="r", role="fasttrack", issue=5,
                         model="m", github_token="ghs_secret_token",
                         on_phase=phases.append)
    assert outcome.status == "success"
    assert "factory/5-x" in git_branches(origin)
    gh_log = (out / "gh.log").read_text()
    assert "pr create" in gh_log
    assert "issue comment" in gh_log
    assert "factory-fast-track-done" in gh_log
    assert "https://github.com/o/r/pull/42" in gh_log
    assert "waiting for tests" in phases
    assert "pushing the branch" in phases
    cwd = Path(next(out.glob("cwd-*.txt")).read_text().strip())
    assert not cwd.exists()
    assert "ghs_secret_token" not in outcome.transcript


def test_observer_resume_on_red(tmp_path, monkeypatch):
    cfg, runner, out, origin = build_observer_runner(
        tmp_path, monkeypatch, test_command="echo boom; exit 1")
    phases = []
    outcome = runner.run(owner="o", repo="r", role="fasttrack", issue=5,
                         model="m", github_token="t", on_phase=phases.append)
    assert outcome.status == "error"
    assert outcome.error and "Tests failed" in outcome.error
    assert "factory/5-x" not in git_branches(origin)
    prompts = captured_prompts(out)
    assert len(prompts) == 3  # initial + two fix resumes
    assert "Tests failed" in prompts[1]
    assert "boom" in prompts[1]
    assert "echo boom; exit 1" in prompts[1]
    assert "waiting for tests" in phases
    assert "fixing failing tests" in phases
    assert "pushing the branch" not in phases
    assert not (out / "gh.log").exists() or "pr create" not in (out / "gh.log").read_text()
    cwd = Path(next(out.glob("cwd-*.txt")).read_text().strip())
    assert not cwd.exists()


def test_observer_skip_when_no_branch(tmp_path, monkeypatch):
    cfg, runner, out, origin = build_observer_runner(
        tmp_path, monkeypatch, commit_factory_branch=False)
    phases = []
    outcome = runner.run(owner="o", repo="r", role="intake", issue=5,
                         model="m", github_token="t", on_phase=phases.append)
    assert outcome.status == "success"
    assert "factory/5-x" not in git_branches(origin)
    assert len(captured_prompts(out)) == 1
    assert "waiting for tests" not in phases
    assert "pushing the branch" not in phases
    assert not (out / "gh.log").exists()
    cwd = Path(next(out.glob("cwd-*.txt")).read_text().strip())
    assert not cwd.exists()


def test_observer_push_when_test_command_null(tmp_path, monkeypatch):
    cfg, runner, out, origin = build_observer_runner(
        tmp_path, monkeypatch, test_command=None)
    phases = []
    outcome = runner.run(owner="o", repo="r", role="fasttrack", issue=5,
                         model="m", github_token="t", on_phase=phases.append)
    assert outcome.status == "success"
    assert "factory/5-x" in git_branches(origin)
    assert "waiting for tests" not in phases
    assert "pushing the branch" in phases
    assert "pr create" in (out / "gh.log").read_text()


def test_load_test_command_and_inspect_branch(tmp_path):
    origin = make_consuming_repo(tmp_path, profile=_observer_profile("pytest -q"))
    assert load_test_command(origin) == "pytest -q"
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)],
                   check=True, capture_output=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(["git", "checkout", "-b", "factory/5-x"], cwd=clone, check=True,
                   env=env, capture_output=True)
    (clone / "x.txt").write_text("x")
    subprocess.run(["git", "add", "x.txt"], cwd=clone, check=True, env=env, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=clone, check=True, env=env, capture_output=True)
    assert inspect_pushable_branch(clone, env) == "factory/5-x"
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True,
                   env=env, capture_output=True)
    assert inspect_pushable_branch(clone, env) is None
    null_dir = tmp_path / "null-profile"
    (null_dir / ".factory").mkdir(parents=True)
    (null_dir / ".factory" / "profile.json").write_text(
        json.dumps({"commands": {"test": None}}))
    assert load_test_command(null_dir) is None

