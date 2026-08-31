"""Every run says what is expected of the next actor — in both engines.

The wording lives in one file (handbook/next-step.json) precisely so the two
engines cannot drift, so these tests render the *same* table through both
renderers and require the same body out. The Actions half is a Python script
in the factory repo, loaded here by path — the same file the pipeline runs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from factory_orchestrator import next_step as ns
from factory_orchestrator.guards import report_next_step

from .fake_repo import FakeRepo

ROOT = Path(__file__).resolve().parents[2]
TABLE = json.loads((ROOT / "handbook" / "next-step.json").read_text())


def _actions_renderer():
    spec = importlib.util.spec_from_file_location(
        "say_next_step", ROOT / "scripts" / "say_next_step.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ACTIONS = _actions_renderer()

# Every state label the factory creates has to have an answer: a state with no
# entry is exactly the silence this table exists to remove.
STATES = [
    "factory:backlog", "factory:release-planning", "factory:release-ready",
    "factory:release-approved", "factory:intake", "factory:spec-ready",
    "factory:spec-approved", "factory:planned", "factory:design-ready",
    "factory:design-approved", "factory:ready", "factory:in-review",
    "factory:in-test", "factory:ready-to-ship", "factory:on-epic",
    "factory:in-staging", "factory:deployed", "factory:fast-track",
    "factory:blocked", "factory:incident", "factory:profile",
]


def test_the_table_answers_every_state():
    assert set(TABLE["states"]) == set(STATES)
    for state, entry in TABLE["states"].items():
        assert entry["who"].strip(), state
        assert entry["how"].strip(), state


@pytest.mark.parametrize("state", STATES + [None])
def test_both_engines_render_the_same_notice(state):
    """The Actions script and this engine must produce identical bodies."""
    mine = ns.render(TABLE, "implementer", 198, state, ["boss"])
    theirs = ACTIONS.render(TABLE, "implementer", 198, state, ["boss"])
    # The Actions renderer appends the agent marker itself; this engine's
    # caller does (guards.report_next_step), so compare without it.
    assert theirs.replace(f"\n{ACTIONS.AGENT_MARK}", "") == mine


def test_the_notice_names_the_state_and_the_move():
    body = ns.render(TABLE, "implementer", 198, "factory:in-review", [])
    assert "#198 is now at `factory:in-review`" in body
    assert "Start the Reviewer" in body  # the Console button
    assert "role: `reviewer`, issue `198`" in body  # the Actions path
    assert "<!-- factory-next:factory:in-review -->" in body


def test_a_gate_notice_names_its_approvers():
    body = ns.render(TABLE, "intake", 250, "factory:spec-ready", ["alice", "bob"])
    assert "gate G1 — @alice, @bob" in body
    empty = ns.render(TABLE, "intake", 250, "factory:spec-ready", [])
    assert "any owner, member or collaborator" in empty


def test_an_issue_off_the_rail_still_gets_an_answer():
    body = ns.render(TABLE, "intake", 7, None, [])
    assert "carrying no `factory:*` state" in body
    assert "<!-- factory-next:none -->" in body


def test_state_is_read_past_the_markers():
    assert ns.state_of(["factory:ready", "factory:in-progress"]) == "factory:ready"
    assert ns.state_of(["factory:release", "factory:release-ready"]) == "factory:release-ready"
    assert ns.state_of(["factory:in-progress"]) is None
    assert ns.state_of(["factory:ready"]) == ACTIONS.state_of(["factory:ready"])


def test_the_same_notice_is_not_repeated():
    said = [{"body": "hello"}, {"body": "x\n<!-- factory-next:factory:in-review -->"}]
    assert ns.already_said(said, "factory:in-review") is True
    assert ACTIONS.already_said(said, "factory:in-review") is True


def test_a_re_entered_state_is_announced_again():
    """review → ready → review is two waits, and each one has to be said."""
    said = [
        {"body": "a\n<!-- factory-next:factory:in-review -->"},
        {"body": "b\n<!-- factory-next:factory:ready -->"},
    ]
    assert ns.already_said(said, "factory:in-review") is False
    assert ACTIONS.already_said(said, "factory:in-review") is False


# -- the guard that posts it -------------------------------------------------

def _repo(labels: list[str], comments=None) -> FakeRepo:
    return FakeRepo(
        {5: {"number": 5, "title": "task(3): add endpoint",
             "labels": [{"name": x} for x in labels],
             "user": {"type": "User"}, "state": "open", "milestone": None}},
        {5: comments} if comments else {},
    )


def test_the_guard_posts_the_notice_with_the_agent_marker():
    repo = _repo(["factory:in-review"])
    report_next_step(repo, 5, "implementer", ROOT)
    assert len(repo.comments[5]) == 1
    body = repo.comments[5][0]["body"]
    assert "**Next: a human, then the Reviewer.**" in body
    assert body.rstrip().endswith("<!-- factory-agent -->")


def test_the_guard_reads_the_approver_list_off_the_repo():
    """A gate notice has to name who can act, or it is not an instruction."""
    repo = _repo(["factory:ready"])
    repo.get_file = lambda path, ref=None: json.dumps({"implementation": ["boss"]})
    report_next_step(repo, 5, "dispatch", ROOT)
    assert "the implementation approvers — @boss" in repo.comments[5][0]["body"]


def test_the_guard_says_it_once():
    repo = _repo(["factory:in-review"])
    report_next_step(repo, 5, "implementer", ROOT)
    report_next_step(repo, 5, "implementer", ROOT)
    assert len(repo.comments[5]) == 1


def test_the_guard_reads_the_state_the_role_left_behind():
    """The marker is still on the issue when this runs — it is cleared last."""
    repo = _repo(["factory:ready", "factory:in-progress"])
    report_next_step(repo, 5, "dispatch", ROOT)
    assert "now at `factory:ready`" in repo.comments[5][0]["body"]


def test_no_table_means_no_notice_rather_than_a_failed_run(tmp_path):
    repo = _repo(["factory:in-review"])
    report_next_step(repo, 5, "implementer", tmp_path)  # an older factory ref
    assert repo.comments.get(5, []) == []
