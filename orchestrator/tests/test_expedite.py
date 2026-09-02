"""Expedite mode (FACTORY.md §4a) — the parts fixtures cannot reach.

The routing decisions themselves are pinned by the shared conformance
fixtures, which both engines run. Three things sit outside them and are
tested here:

* the auto-advance map is the *same table* in both engines — the fixtures
  would catch a divergence only for a state they happen to cover, and a map
  is exactly the kind of thing that grows a row on one side;
* task→epic inheritance, which the chain reads and the router never does
  (no routed event carries "a role just finished on this task");
* the two gates the map must never contain, asserted against the map rather
  than against a scenario, so a future row cannot quietly ship an epic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from factory_orchestrator.router import (
    EPIC_READY,
    EXPEDITE,
    EXPEDITE_MAP,
    expedited_next,
    expedited_ready_tasks,
    is_expedited,
)

from .fake_repo import FakeRepo

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "factory-pipeline.yml"


def _js_map(script: str) -> dict[str, str]:
    body = re.search(r"const EXPEDITE_MAP = \{(.*?)\};", script, re.S)
    assert body, "no EXPEDITE_MAP in this script"
    return dict(re.findall(r"'([^']+)':\s*'([^']+)'", body.group(1)))


def test_both_engines_carry_the_same_auto_advance_map():
    doc = yaml.safe_load(WORKFLOW.read_text())
    route = next(s for s in doc["jobs"]["route"]["steps"] if s.get("id") == "route")
    js = _js_map(route["with"]["script"])
    assert js == EXPEDITE_MAP, (
        "the Actions router and this engine disagree about what expedite advances; "
        "the map moves in one PR or not at all"
    )


@pytest.mark.parametrize("state", [
    EPIC_READY,            # gate GS — releasing the epic to staging
    "factory:in-staging",  # gate G3 — promotion to production
    "factory:deployed",
    "factory:backlog",     # upstream of the spec: G0 is never waived
    "factory:intake",
])
def test_the_map_never_advances_a_ship_gate_or_the_backlog(state):
    assert state not in EXPEDITE_MAP
    assert expedited_next(state, epics=True) is None
    assert expedited_next(state, epics=False) is None


def test_assembly_runs_itself_only_when_there_is_an_epic_branch():
    # With no epic branch the Release Manager's first merge lands on the
    # integration branch and IS the staging deploy, so the chain stops.
    assert expedited_next("factory:ready-to-ship", epics=True) == "release"
    assert expedited_next("factory:ready-to-ship", epics=False) is None


def test_a_task_inherits_expedite_from_its_epic():
    world = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": EXPEDITE}]},
        8: {"number": 8, "title": "task(5) do the thing", "body": "Part of o/r#5",
            "labels": [{"name": "factory:in-review"}]},
    }, {})
    assert is_expedited(world, world.issues[8]) is True


def test_a_task_is_not_expedited_when_its_epic_is_not():
    world = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": "factory:design-approved"}]},
        8: {"number": 8, "title": "task(5) do the thing", "body": "Part of o/r#5",
            "labels": [{"name": "factory:in-review"}]},
    }, {})
    assert is_expedited(world, world.issues[8]) is False


def test_the_marker_is_never_copied_so_removal_reaches_every_task():
    """Removing it from the epic must stop its tasks in the same instant."""
    world = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": []},
        8: {"number": 8, "title": "task(5) do the thing", "body": "Part of o/r#5",
            "labels": [{"name": "factory:in-test"}]},
    }, {})
    assert is_expedited(world, world.issues[8]) is False
    world.add_labels(5, [EXPEDITE])
    assert is_expedited(world, world.issues[8]) is True
    world.remove_label(5, EXPEDITE)
    assert is_expedited(world, world.issues[8]) is False


def test_a_cross_repo_epic_without_access_is_not_expedited():
    """Better to ask a human than to guess: the un-expedited path is safe."""
    world = FakeRepo({
        8: {"number": 8, "title": "task(250) contact column",
            "body": "Part of o/backend#250", "labels": [{"name": "factory:ready"}]},
    }, {})
    assert is_expedited(world, world.issues[8], port_for=None) is False


def test_the_title_wins_when_the_body_marker_disagrees():
    world = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": EXPEDITE}]},
        8: {"number": 8, "title": "task(5) do the thing",
            "body": "Part of o/other#99", "labels": [{"name": "factory:ready"}]},
    }, {})
    # task(5) is authoritative for the number, so the o/other repo is dropped
    # and #5 is read here — the same rule the re-dispatch already follows (§7).
    assert is_expedited(world, world.issues[8]) is True


def test_the_dispatch_fan_out_skips_live_and_blocked_tasks():
    world = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": EXPEDITE}]},
        8: {"number": 8, "title": "task(5) one", "labels": [{"name": "factory:ready"}]},
        9: {"number": 9, "title": "task(5) two",
            "labels": [{"name": "factory:ready"}, {"name": "factory:in-progress"}]},
        10: {"number": 10, "title": "task(5) three",
             "labels": [{"name": "factory:ready"}, {"name": "factory:blocked"}]},
        11: {"number": 11, "title": "task(6) elsewhere", "labels": [{"name": "factory:ready"}]},
        12: {"number": 12, "title": "Not a task", "labels": [{"name": "factory:ready"}]},
    }, {})
    assert expedited_ready_tasks(world, 5) == [("o/r", 8)]


def test_the_dispatch_fan_out_reaches_a_cross_repo_epics_sibling_repos():
    """The epic is in the coordination repo; its tasks are not (FACTORY.md §7).

    Searching only the epic's own repo is what left every sibling repo's task
    parked at `factory:ready` under an expedited epic — the marker waived the
    click, and nothing was ever going to look for them over there.
    """
    epic_repo = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": EXPEDITE}]},
        8: {"number": 8, "title": "task(5) backend", "labels": [{"name": "factory:ready"}]},
    }, {}, owner="o", repo="backend")
    ui = FakeRepo({
        3: {"number": 3, "title": "task(5) the screen", "body": "Part of o/backend#5",
            "labels": [{"name": "factory:ready"}]},
        4: {"number": 4, "title": "task(5) already running", "body": "Part of o/backend#5",
            "labels": [{"name": "factory:ready"}, {"name": "factory:in-progress"}]},
        # Same number, another repo's epic: without the qualified marker this
        # would be indistinguishable from one of ours.
        6: {"number": 6, "title": "task(5) someone else's epic",
            "body": "Part of o/other#5", "labels": [{"name": "factory:ready"}]},
        # An unqualified task in a sibling repo names no epic repo at all, so
        # it cannot be claimed by this one.
        7: {"number": 7, "title": "task(5) unqualified", "labels": [{"name": "factory:ready"}]},
        # The title is authoritative for the number (§7), so a marker naming a
        # different one forfeits its repo — this is o/ui's own task(5).
        9: {"number": 9, "title": "task(5) stray marker", "body": "Part of o/backend#99",
            "labels": [{"name": "factory:ready"}]},
    }, {}, owner="o", repo="ui")

    assert expedited_ready_tasks(epic_repo, 5, [ui]) == [("o/backend", 8), ("o/ui", 3)]


def test_a_sibling_repo_that_cannot_be_listed_does_not_lose_the_others():
    class Unreachable(FakeRepo):
        def list_issues(self, **kw):
            raise RuntimeError("403")

    epic_repo = FakeRepo({
        5: {"number": 5, "title": "Epic", "labels": [{"name": EXPEDITE}]},
        8: {"number": 8, "title": "task(5) backend", "labels": [{"name": "factory:ready"}]},
    }, {}, owner="o", repo="backend")
    assert expedited_ready_tasks(
        epic_repo, 5, [Unreachable({}, {}, owner="o", repo="ui")]) == [("o/backend", 8)]
