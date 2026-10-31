"""hooks/protect-branches.py, and how the orchestrator wires it into a run."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from factory_orchestrator.role_runner import install_branch_guard

from .test_graph import ConfiguredRepo, graph_with, issue

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "protect-branches.py"


def stub(bin_dir: Path, name: str, script: str) -> None:
    p = bin_dir / name
    p.write_text(f"#!/bin/bash\n{script}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def run_hook(tmp_path, command, *, guard=None, base="staging", remote_exists=True, tool="Bash"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub(bin_dir, "gh", f'echo "{base}"')
    stub(bin_dir, "git", f'[ "$1" = "ls-remote" ] && exit {0 if remote_exists else 2}\necho feature')
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    env.pop("FACTORY_STAGING_GUARD", None)
    if guard:
        env["FACTORY_STAGING_GUARD"] = guard
    return subprocess.run([sys.executable, str(HOOK)], env=env, capture_output=True, text=True,
                          input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}))


@pytest.mark.parametrize("command", [
    "git push origin main", "git push origin HEAD:main", "git push origin +master",
    "cd repo && git push origin refs/heads/main",
])
def test_main_is_always_refused(tmp_path, command):
    assert run_hook(tmp_path, command).returncode == 2
    assert run_hook(tmp_path, command, guard="open").returncode == 2


def test_a_closed_run_cannot_reach_staging(tmp_path):
    for command in ("git push origin HEAD:staging", "gh pr merge 12 --merge",
                    "gh api -X PUT repos/o/r/pulls/12/merge", "gh api -X PATCH repos/o/r/git/refs/heads/staging"):
        r = run_hook(tmp_path, command, guard="closed")
        assert r.returncode == 2, command
        assert "release to staging (GS)" in r.stderr


def test_an_approved_run_can(tmp_path):
    assert run_hook(tmp_path, "git push origin HEAD:staging", guard="open").returncode == 0
    assert run_hook(tmp_path, "gh pr merge 12 --merge", guard="open").returncode == 0


def test_a_merge_onto_main_is_refused_even_when_staging_is_open(tmp_path):
    assert run_hook(tmp_path, "gh pr merge 12 --merge", guard="open", base="main").returncode == 2


def test_ordinary_work_is_untouched(tmp_path):
    for command in ("git push origin factory/40-status-map", "gh pr view 12", "pytest -q",
                    "git merge origin/staging"):
        assert run_hook(tmp_path, command, guard="closed").returncode == 0, command
    # The Release Manager's phase 1: a task PR onto the epic branch.
    assert run_hook(tmp_path, "gh pr merge 12 --merge", guard="closed",
                    base="factory/epic-34").returncode == 0


def test_a_missing_integration_branch_can_be_created(tmp_path):
    command = "git push origin origin/main:refs/heads/staging"
    assert run_hook(tmp_path, command, guard="closed", remote_exists=False).returncode == 0
    assert run_hook(tmp_path, command, guard="closed", remote_exists=True).returncode == 2


def test_the_engine_leaves_staging_writable_under_actions(tmp_path):
    assert run_hook(tmp_path, "git push origin HEAD:staging").returncode == 0


def test_the_guard_is_wired_into_the_runs_own_settings(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    settings = install_branch_guard(home, HOOK.parents[1])
    hooks = json.loads(settings.read_text())["hooks"]["PreToolUse"]
    assert hooks[0]["matcher"] == "Bash|mcp__github__.*"
    assert str(HOOK) in hooks[0]["hooks"][0]["command"]


def test_a_missing_script_wires_nothing_rather_than_refusing_every_call(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert install_branch_guard(home, tmp_path) is None
    assert list(home.iterdir()) == []


def test_a_real_run_passes_the_guard_to_claude(tmp_path):
    from factory_orchestrator.config import load_config
    from factory_orchestrator.role_runner import FactorySource

    from .test_config import BASE
    from .test_role_runner import (
        LocalCloneRunner,
        make_consuming_repo,
        make_fake_claude,
        make_local_factory,
    )
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60"})
    factory = make_local_factory(tmp_path)
    (factory / "hooks").mkdir(exist_ok=True)
    (factory / "hooks" / "protect-branches.py").write_text("")
    out = tmp_path / "captured"
    runner = LocalCloneRunner(cfg, FactorySource(cfg, local_path=str(factory)),
                              workspace_root=str(tmp_path / "ws"),
                              claude_bin=str(make_fake_claude(tmp_path, out)),
                              origin=make_consuming_repo(tmp_path))
    (tmp_path / "ws").mkdir()
    runner.run(owner="o", repo="r", role="qa", issue=5, model="m", github_token="t",
               integration_branch="develop")
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--settings") + 1].endswith("factory-guard-settings.json")


class Policy(ConfiguredRepo):
    def __init__(self, *a, epics=True, **kw):
        super().__init__(*a, **kw)
        self.files = {**ConfiguredRepo.files,
                      ".github/factory-branches.json": json.dumps({"epics": epics, "staging": "staging"})}


def released(tmp_path, labels, role="release", *, epics=True, moves=False):
    tmp_path.mkdir(exist_ok=True)
    world = Policy({9: issue(9, "Epic", labels)}, epics=epics)
    world.branch_shas["staging"] = "aaa"

    def behave(w, n):
        w.create_comment(n, "done\n\n<!-- factory-agent -->")
        if moves:
            w.branch_shas["staging"] = "bbb"
    graph, engine, ledger, runner = graph_with(tmp_path, world, {role: behave})
    seen = {}
    real = runner.run

    def spy(**kw):
        seen.update(kw)
        return real(**kw)
    runner.run = spy
    from factory_orchestrator.graph import Processor
    Processor(engine, graph)("workflow_dispatch", {
        "inputs": {"role": role, "issue_number": 9}, "repository": {"full_name": "o/r"}})
    return world, ledger, seen


def test_only_release_behind_the_gate_opens_staging(tmp_path):
    assert released(tmp_path / "a", ["factory:epic-ready"])[2]["staging_open"] is True
    assert released(tmp_path / "b", ["factory:design-approved"])[2]["staging_open"] is False
    assert released(tmp_path / "c", ["factory:epic-ready"], role="qa")[2]["staging_open"] is False
    # No epic branch: a person started this release.
    assert released(tmp_path / "d", ["factory:ready-to-ship"], epics=False)[2]["staging_open"] is True


def test_a_move_without_approval_is_said_on_the_issue(tmp_path):
    world, ledger, _ = released(tmp_path / "a", ["factory:in-test"], role="qa", moves=True)
    assert any("`staging` changed during this qa run" in c["body"] for c in world.comments[9])
    assert json.loads(ledger.list_runs(repo="o/r", issue=9)[0]["guards"])["staging_moved"] is True


def test_an_approved_move_says_nothing(tmp_path):
    world, *_ = released(tmp_path / "a", ["factory:epic-ready"], moves=True)
    assert not any("changed during this" in c["body"] for c in world.comments[9])


