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
)

from .test_config import BASE

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_local_factory(tmp_path: Path) -> Path:
    src = tmp_path / "factory"
    (src / "commands").mkdir(parents=True)
    (src / "FACTORY.md").write_text("# The Software Factory\nHANDBOOK BODY\n")
    (src / "commands" / "intake.md").write_text("# Intake\nROLE BODY\n")
    return src


def make_fake_claude(tmp_path: Path, out_dir: Path, *, exit_code: int = 0,
                     sleep: float = 0) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
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
sleep {sleep}
echo "fake transcript with $GH_TOKEN inside"
exit {exit_code}
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def make_consuming_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin" / "r"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("hello")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["git", "init", "-q"], ["git", "add", "."],
                ["git", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env, capture_output=True)
    return repo


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
