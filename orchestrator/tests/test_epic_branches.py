"""Document routing (FACTORY.md §6/§6b) at the gate merges — the Python twin
of scenario 20 in scripts/test-router.js. Both engines must retarget gate
document PRs the same way, so a change here lands with the JS scenario
moving in the same PR.

The target is the first rung of §6's ladder that applies: the epic branch
under `epics: true`, else the integration branch, else — only for a repo with
no integration branch at all — the default branch."""

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


def test_design_gate_adopts_an_epic_whose_spec_merged_to_the_default_branch():
    # The spec merged to the default branch before the flip, so no epic branch
    # exists yet. The design gate is an adoption point too: the branch is cut
    # from the default branch — which carries that merged spec — and the design
    # PR is retargeted onto it. No task PR can have merged yet, so the cut
    # loses nothing.
    w = FakeRepo(issues=_issue(5, ["factory:design-ready"]))
    w.open_prs["o:factory/5-design"] = [{"number": 9, "base": {"ref": "main"}}]
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "dispatch"
    assert "factory/epic-5" in w.branches
    assert w.merged_bases[9] == "factory/epic-5"


def test_a_hand_merged_gate_document_still_adopts_the_epic():
    # The gate is reachable by a human merging the document PR themselves —
    # the factory says so on the issue — which leaves nothing open to
    # retarget. Adoption used to hang off that PR, so this route silently
    # condemned the epic to legacy routing and every task PR it later opened
    # went to the integration branch instead of the epic branch.
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "planner"
    assert "factory/epic-5" in w.branches


def test_epics_off_sends_the_gate_document_to_the_integration_branch():
    # No epic branch is cut, and the document does NOT go to the default
    # branch: with epics off the integration branch is where the stages read.
    w = FakeRepo(issues=_issue(5, ["factory:design-ready"]))
    w.open_prs["o:factory/5-design"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w).route(*_approved(w, 5))
    assert "factory/epic-5" not in w.branches
    assert w.merged_bases[9] == "staging"


def test_design_gate_follows_an_existing_epic_branch():
    w = FakeRepo(issues=_issue(5, ["factory:design-ready"]))
    w.branches.append("factory/epic-5")
    w.open_prs["o:factory/5-design"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w, EPICS_ON).route(*_approved(w, 5))
    assert w.merged_bases[9] == "factory/epic-5"


def test_epics_off_retargets_off_a_stale_epic_branch_onto_integration():
    # A flip back to epics:false: the PR comes off the epic branch, but it
    # lands on the integration branch, never on the default branch.
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.branches.append("factory/epic-5")
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "factory/epic-5"}}]
    _router(w).route(*_approved(w, 5))
    assert w.merged_bases[9] == "staging"


def test_no_integration_branch_is_the_one_case_documents_reach_the_default():
    # required:false means this repo opted out of staging entirely, so there
    # is nowhere else its documents could go.
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w, {"required": False}).route(*_approved(w, 5))
    assert w.merged_bases[9] == "main"
    assert w.branches == ["main"]


def test_a_repo_profile_renames_the_integration_branch():
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    cfg = RepoConfig(approvers=APPROVERS, branches={},
                     profile={"branches": {"staging": "develop"}})
    Router(w, cfg).route(*_approved(w, 5))
    assert w.merged_bases[9] == "develop"


def test_absent_policy_still_routes_documents_through_staging():
    # An absent file means epics:false AND staging:"staging" required — the
    # defaults — so a document PR based on the default branch is retargeted.
    w = FakeRepo(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    _router(w).route(*_approved(w, 5))
    assert w.merged_bases[9] == "staging"
    assert "factory/epic-5" not in w.branches


def test_approved_on_on_epic_explains_and_routes_nothing():
    w = FakeRepo(issues=_issue(5, ["factory:on-epic"]))
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "none"
    bodies = [c["body"] for c in w.comments.get(5, [])]
    assert any("epic branch" in b for b in bodies)


def test_a_repo_that_refuses_the_branch_still_gets_its_gate_approved():
    # Losing the approval is worse than the epic finishing on default-branch
    # routing, so branch creation is best-effort — and a PR is never
    # retargeted onto a branch that does not exist.
    class Refuses(FakeRepo):
        def create_branch(self, name, from_branch):
            raise RuntimeError("refs/heads/factory/epic-5 is protected")

    w = Refuses(issues=_issue(5, ["factory:spec-ready"]))
    w.open_prs["o:factory/5-spec"] = [{"number": 9, "base": {"ref": "main"}}]
    r = _router(w, EPICS_ON).route(*_approved(w, 5))
    assert r.role == "planner"
    assert "factory/epic-5" not in w.branches
    assert w.merged_bases[9] == "main"
