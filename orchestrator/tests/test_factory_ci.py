"""The factory as a repo's CI (FACTORY.md §6c): QA's verdict as `factory/tests`."""

from __future__ import annotations

import json

from factory_orchestrator.factory_ci import (
    CI_CONTEXT,
    ci_mode,
    find_task_pr,
    post_qa_status,
)
from factory_orchestrator.graph import Processor

from .fake_repo import FakeRepo
from .test_graph import APPROVERS, flip, graph_with, issue


class CiRepo(FakeRepo):
    def __init__(self, *a, ci: str | None = "factory", **kw):
        super().__init__(*a, **kw)
        settings = {"engine": "langgraph"} | ({"ci": ci} if ci else {})
        self.files = {
            ".github/factory-orchestrator.json": json.dumps(settings),
            ".github/factory-approvers.json": json.dumps(APPROVERS),
        }

    def get_file(self, path, ref=None):
        return self.files.get(path)


def pr(number, ref, sha, body=""):
    return {"number": number, "head": {"ref": ref, "sha": sha}, "body": body,
            "base": {"ref": "factory/epic-34"}}


def task_world(labels, ci="factory", prs=None):
    world = CiRepo({40: issue(40, "task(34): status map", labels)}, ci=ci)
    world.open_prs["any"] = prs if prs is not None else [
        pr(99, "factory/12-other", "bbb"),
        pr(101, "factory/40-sheets-status-map", "abc1234"),
    ]
    return world


def test_ci_mode_defaults_to_actions():
    assert ci_mode(task_world([], ci=None)) == "actions"
    assert ci_mode(task_world([], ci="jenkins")) == "actions"
    assert ci_mode(task_world([])) == "factory"


def test_task_pr_is_found_by_branch_then_by_closes():
    world = task_world([])
    assert find_task_pr(world, 40)["number"] == 101
    world.open_prs["any"] = [pr(7, "feature/x", "c", body="Work.\n\nCloses #40")]
    assert find_task_pr(world, 40)["number"] == 7
    world.open_prs["any"] = [pr(7, "feature/x", "c", body="Closes #400")]
    assert find_task_pr(world, 40) is None


def test_ready_to_ship_posts_green_on_the_pr_head():
    world = task_world(["factory:ready-to-ship"])
    assert post_qa_status(world, 40, "https://sf/runs/r1") == "success"
    sha, state, context, _desc, url = world.statuses[0]
    assert (sha, state, context, url) == ("abc1234", "success", CI_CONTEXT, "https://sf/runs/r1")


def test_back_to_ready_posts_red():
    world = task_world(["factory:ready"])
    assert post_qa_status(world, 40, "u") == "failure"
    assert world.statuses[0][1] == "failure"


def test_no_verdict_posts_nothing():
    for labels in (["factory:in-test", "factory:blocked"],
                   ["factory:ready-to-ship", "factory:blocked"],
                   ["factory:in-test"]):
        world = task_world(labels)
        assert post_qa_status(world, 40, "u") is None
        assert world.statuses == []


def test_actions_repos_are_left_alone():
    world = task_world(["factory:ready-to-ship"], ci=None)
    assert post_qa_status(world, 40, "u") is None
    assert world.statuses == []


def test_a_status_github_refuses_never_fails_the_run():
    world = task_world(["factory:ready-to-ship"])

    def refuse(*_a, **_k):
        raise RuntimeError("403 Resource not accessible by integration")
    world.create_status = refuse
    assert post_qa_status(world, 40, "u") is None


def test_a_qa_run_posts_the_status_and_records_it(tmp_path):
    world = task_world(["factory:in-test"])
    graph, engine, ledger, runner = graph_with(tmp_path, world, {
        "qa": lambda w, n: flip(w, n, "factory:in-test", "factory:ready-to-ship")})
    Processor(engine, graph)("workflow_dispatch", {
        "inputs": {"role": "qa", "issue_number": 40},
        "repository": {"full_name": "o/r"}})
    assert [c["role"] for c in runner.calls] == ["qa"]
    run = ledger.list_runs(repo="o/r", issue=40)[0]
    assert world.statuses and world.statuses[0][:3] == ("abc1234", "success", CI_CONTEXT)
    assert world.statuses[0][4].endswith(f"/runs/{run['id']}")
    assert json.loads(run["guards"])["ci"] == "success"
