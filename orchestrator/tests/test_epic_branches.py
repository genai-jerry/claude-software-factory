"""Epic-branch policy (FACTORY.md §6b) at the gate merges — the Python twin
of scenario 20 in scripts/test-router.js. Both engines must retarget gate
document PRs the same way, so a change here lands with the JS scenario
moving in the same PR."""

from __future__ import annotations

from factory_orchestrator.router import RepoConfig, Router

from .fake_repo import FakeRepo

EPICS_ON = {"staging": "staging", "required": True, "auto_create": True, "epics": True}
APPROVERS = {"spec": ["boss"], "design": ["boss"]}


def _issue(n, labels):
    return {n: {"number": n, "title": "Epic", "state": "open",
                "user": {"type": "User"}, "milestone": None,
                "labels": [{"name": x} for x in labels]}}


def _approved(world, n):
    return ("issue_comment", {
        "action": "created", "issue": world.issues[n],
        "repository": {"default_branch": "main"},
        "comment": {"body": "Approved", "user": {"login": "boss", "type": "User"},
                    "author_association": "OWNER"}})


def _router(world, branches=None):
    return Router(world, RepoConfig(approvers=APPROVERS, branches=branches or {}))


def test_spec_gate_adopts_an_inflight_epic():
    # A spec PR still based on the default branch: the G1 approval creates
    # factory/epic-5 and retargets the PR before the squash merge.
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "planner"
    assert "factory/epic-5" in w.branches
    assert w.merged_bases[9] == "factory/epic-5"


def test_spec_gate_merges_a_correctly_based_pr_untouched():
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.branches.append("factory/epic-5")
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "factory/epic-5"}}]
    _router(w, EPICS_ON).route(*_approved(w, 5))
    assert w.merged_bases[9] == "factory/epic-5"
    assert w.branches.count("factory/epic-5") == 1


def test_design_gate_leaves_a_legacy_epic_on_legacy_routing():
    # Spec already merged to the default branch (no epic branch exists), so
    # the epic finishes as it started: design merges to main, no adoption.
    w = FakeRepo(issues=_issue(5, ["factory:design-ready"]))
    w.open_prs["o:factory/5-design"] = [{"number": 9, "base": {"ref": "main"}}]
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "dispatch"
    assert "factory/epic-5" not in w.branches
    assert w.merged_bases[9] == "main"


def test_design_gate_follows_an_existing_epic_branch():
    w = FakeRepo(issues=_issue(5, ["factory:design-ready"]))
    w.branches.append("factory/epic-5")
    w.open_prs["o:factory/5-design"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w, EPICS_ON).route(*_approved(w, 5))
    assert w.merged_bases[9] == "factory/epic-5"


def test_epics_off_retargets_back_to_the_default_branch():
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.branches.append("factory/epic-5")
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "factory/epic-5"}}]
    _router(w).route(*_approved(w, 5))
    assert w.merged_bases[9] == "main"


def test_absent_policy_changes_nothing():
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w).route(*_approved(w, 5))
    assert w.merged_bases[9] == "main"
    assert w.branches == ["main"]


def test_approved_on_on_epic_explains_and_routes_nothing():
    w = FakeRepo(issues=_issue(5, ["factory:on-epic"]))
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "none"
    bodies = [c["body"] for c in w.comments.get(5, [])]
    assert any("epic branch" in b for b in bodies)
