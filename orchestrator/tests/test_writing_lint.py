"""Report-only writing scores: the run's own agent comments, through the shared checker."""

import shutil
from pathlib import Path

import pytest

from factory_orchestrator.writing_lint import score_new_comments

from .fake_repo import FakeRepo

FACTORY = Path(__file__).resolve().parents[2]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

GOOD = ("**Spec ready for #5.**\n**You need to:** review the PR, then comment `Approved`.\n"
        "Next: the Planner.\n\n<!-- factory-agent -->")
LONG = ("This comment explains at great length how the factory decided what to do and why "
        "it works the way it does, without ever saying what the reader must do now.\n\n"
        "<!-- factory-agent -->")


def world_with(comments):
    world = FakeRepo({5: {"number": 5, "title": "x", "labels": []}})
    world.comments[5] = [{"body": b} for b in comments]
    return world


@needs_node
def test_scores_only_the_agent_comments_this_run_added():
    world = world_with(["old agent note <!-- factory-agent -->", "a human reply", GOOD, LONG,
                        "another human reply"])
    out = score_new_comments(world, 5, before_count=1, factory_path=FACTORY)
    assert out["summary"]["comments"] == 2
    assert out["summary"]["ok"] == 1
    assert any("sentence" in p for p in out["comments"][1]["problems"])


@needs_node
def test_nothing_new_is_not_scored():
    assert score_new_comments(world_with([GOOD]), 5, before_count=1, factory_path=FACTORY) is None


def test_no_factory_checkout_or_script_is_not_scored(tmp_path):
    world = world_with([GOOD])
    assert score_new_comments(world, 5, before_count=0, factory_path=None) is None
    assert score_new_comments(world, 5, before_count=0, factory_path=tmp_path) is None


def test_a_failing_read_never_raises(tmp_path):
    class Broken(FakeRepo):
        def list_comments(self, n):
            raise RuntimeError("GitHub is down")
    assert score_new_comments(Broken(), 5, before_count=0, factory_path=FACTORY) is None
