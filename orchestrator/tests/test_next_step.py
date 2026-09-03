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
    "factory:manual-test", "factory:test-passed", "factory:test-failed",
    "factory:epic-ready", "factory:in-staging", "factory:deployed",
    "factory:fast-track", "factory:blocked", "factory:incident",
    "factory:profile",
]

#: The states expedite advances (FACTORY.md §4a), which are exactly the ones
#: that must carry an `expedited` wording variant: telling a reader to press a
#: button the factory is about to press itself is the drift this table exists
#: to prevent.
EXPEDITED_STATES = [
    "factory:spec-ready", "factory:design-ready", "factory:ready",
    "factory:in-review", "factory:in-test", "factory:ready-to-ship",
]


#: The states whose story changes where a repo runs system tests (§4b) — and
#: exactly the ones that carry a `tested` variant. An epic's build is not over
#: when its tasks are, and a landed task waits on cases as well as siblings.
TESTED_STATES = ["factory:design-approved", "factory:on-epic"]


def test_the_table_answers_every_state():
    assert set(TABLE["states"]) == set(STATES)
    for state, entry in TABLE["states"].items():
        assert entry["who"].strip(), state
        assert entry["how"].strip(), state


def test_expedited_variants_cover_the_states_expedite_advances():
    for state in EXPEDITED_STATES:
        variant = TABLE["states"][state].get("expedited")
        assert isinstance(variant, dict), state
        assert variant["who"].strip() and variant["how"].strip(), state
    # And nowhere else: a variant on a state the factory does not advance
    # would promise automation that never comes.
    for state, entry in TABLE["states"].items():
        if state not in EXPEDITED_STATES:
            assert "expedited" not in entry, state


@pytest.mark.parametrize("state", EXPEDITED_STATES)
def test_both_engines_render_the_same_expedited_notice(state):
    mine = ns.render(TABLE, "implementer", 198, state, ["boss"], True)
    theirs = ACTIONS.render(TABLE, "implementer", 198, state, ["boss"], True)
    assert mine in theirs
    # The variant is what got rendered, not the un-expedited wording.
    assert TABLE["states"][state]["how"][:40] not in mine


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


def test_the_guard_reads_a_cross_repo_epics_marker():
    """The wording the user saw was the bug: a click expedite had waived.

    The task is in one repo and its expedited epic in another (FACTORY.md §7),
    so the marker is only reachable through a port on the other repo. The
    Actions engine's twin (scripts/say_next_step.py) does this read over its
    PAT; this one has to match it or the two say opposite things.
    """
    repo = FakeRepo(
        {5: {"number": 5, "title": "task(3): add endpoint",
             "body": "Part of o/backend#3",
             "labels": [{"name": "factory:ready"}],
             "user": {"type": "User"}, "state": "open", "milestone": None}},
        {}, owner="o", repo="ui")
    epic = FakeRepo(
        {3: {"number": 3, "title": "Epic", "labels": [{"name": "factory:expedite"}],
             "user": {"type": "User"}, "state": "open", "milestone": None}},
        {}, owner="o", repo="backend")

    report_next_step(repo, 5, "dispatch", ROOT, port_for=lambda o, r: epic)
    body = repo.comments[5][0]["body"]
    assert "the factory — this task's epic is expedited" in body
    assert "Comment exactly `Approved`" not in body


def test_without_cross_repo_access_the_notice_asks_a_human():
    """Unchanged: an epic this engine cannot read is not an expedited one."""
    repo = FakeRepo(
        {5: {"number": 5, "title": "task(3): add endpoint",
             "body": "Part of o/backend#3",
             "labels": [{"name": "factory:ready"}],
             "user": {"type": "User"}, "state": "open", "milestone": None}},
        {}, owner="o", repo="ui")
    report_next_step(repo, 5, "dispatch", ROOT)
    assert "Comment exactly `Approved`" in repo.comments[5][0]["body"]


def test_tested_variants_cover_the_states_system_tests_change():
    for state in TESTED_STATES:
        variant = TABLE["states"][state].get("tested")
        assert isinstance(variant, dict), state
        assert variant["who"].strip() and variant["how"].strip(), state
    # And nowhere else: a `tested` variant on a state system tests do not
    # change would describe cases that have nothing to do with it.
    for state, entry in TABLE["states"].items():
        if state not in TESTED_STATES:
            assert "tested" not in entry, state


def test_the_three_test_states_name_the_testers_and_the_two_comments():
    """A tester arriving at a case must find the whole control in one place."""
    manual = TABLE["states"]["factory:manual-test"]
    assert "{approvers}" in manual["who"]
    assert "Test Passed" in manual["how"] and "Test Failed" in manual["how"]
    assert "test-plan.md" in manual["how"]
    # A failed case says what is happening for it, not what the reader must do.
    assert "fix" in TABLE["states"]["factory:test-failed"]["how"]


@pytest.mark.parametrize("state", TESTED_STATES)
def test_both_engines_render_the_same_tested_notice(state):
    mine = ns.render(TABLE, "dispatch", 198, state, ["boss"], False, True)
    theirs = ACTIONS.render(TABLE, "dispatch", 198, state, ["boss"], False, True)
    assert theirs.replace(f"\n{ACTIONS.AGENT_MARK}", "") == mine
    # The variant is what got rendered. Both wordings can open on the same
    # sentence (a landed task is still a landed task), so compare on what
    # only the variant says: the cases.
    assert "case" in mine


@pytest.mark.parametrize("state", TESTED_STATES)
def test_without_the_policy_the_plain_wording_stands(state):
    """A repo that has not enabled system tests never sees the variant."""
    plain = ns.render(TABLE, "dispatch", 198, state, ["boss"], False, False)
    assert plain != ns.render(TABLE, "dispatch", 198, state, ["boss"], False, True)
    assert TABLE["states"][state]["how"] in plain
