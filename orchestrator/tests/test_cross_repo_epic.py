"""A cross-repo epic's dependents have to be released too.

FACTORY.md §7 lets an epic live in one repo and its tasks in the repos that
implement them; the task body carries the qualified `Part of owner/repo#N`
marker. The task-closed re-dispatch looked `#N` up in the *task's* repo, where
it is missing (or, worse, is an unrelated issue with that number) — so every
dependent of every closed task in a cross-repo epic was silently never
released, and the chain simply stopped.
"""

from __future__ import annotations

import pytest

from factory_orchestrator.router import RepoConfig, Router, epic_ref_from_body

from .fake_repo import FakeRepo

EPIC_BODY = "Part of genai-jerry/lighthouse-backend#250\n\nChange folder: ...\n"


def task_repo(body: str = EPIC_BODY) -> FakeRepo:
    repo = FakeRepo({
        198: {"number": 198, "title": "task(250): contact column", "body": body,
              "labels": [], "user": {"type": "User"}, "state": "closed",
              "milestone": None},
    })
    repo.owner, repo.repo = "genai-jerry", "lighthouse-ui"
    return repo


def epic_repo(labels: list[str]) -> FakeRepo:
    repo = FakeRepo({
        250: {"number": 250, "title": "Reorganise the list", "body": "",
              "labels": [{"name": x} for x in labels], "user": {"type": "User"},
              "state": "open", "milestone": None},
    })
    repo.owner, repo.repo = "genai-jerry", "lighthouse-backend"
    return repo


def route_close(task: FakeRepo, port_for=None):
    return Router(task, RepoConfig(), port_for=port_for).route(
        "issues",
        {"action": "closed", "issue": task.issues[198],
         "repository": {"full_name": "genai-jerry/lighthouse-ui"}},
    )


class TestEpicRefFromBody:
    def test_reads_the_qualified_marker(self):
        assert epic_ref_from_body(EPIC_BODY) == ("genai-jerry/lighthouse-backend", 250)

    @pytest.mark.parametrize("body,expected", [
        ("Parent: #7", (None, 7)),
        ("Epic: #7", (None, 7)),
        ("Part of #7", (None, 7)),
        ("Part of https://github.com/o/r/issues/7", ("o/r", 7)),
        ("no marker here", (None, None)),
        # Prose that mentions an epic in passing is not a marker.
        ("this was part of the old design, see #7 for why", (None, None)),
    ])
    def test_the_other_forms(self, body, expected):
        assert epic_ref_from_body(body) == expected


class TestCrossRepoRedispatch:
    def test_dispatches_the_epic_in_its_own_repo(self):
        epic = epic_repo(["factory:design-approved"])
        result = route_close(task_repo(), port_for=lambda o, r: epic)
        assert result.role == "dispatch"
        assert result.issue == "250"
        assert result.repo == "genai-jerry/lighthouse-backend"

    def test_reads_the_epic_state_over_there_not_here(self):
        """The task's own repo has no #250 — the old lookup found nothing."""
        epic = epic_repo(["factory:spec-ready"])  # not design-approved
        result = route_close(task_repo(), port_for=lambda o, r: epic)
        assert result.role == "none"

    def test_without_cross_repo_access_it_dispatches_nothing(self):
        result = route_close(task_repo(), port_for=None)
        assert result.role == "none"

    def test_a_same_repo_epic_still_routes_locally(self):
        """The common case keeps working, and carries no target repo."""
        task = FakeRepo({
            5: {"number": 5, "title": "Epic", "body": "",
                "labels": [{"name": "factory:design-approved"}],
                "user": {"type": "User"}, "state": "open", "milestone": None},
            8: {"number": 8, "title": "task(5): step one", "body": "Parent: #5",
                "labels": [], "user": {"type": "User"}, "state": "closed",
                "milestone": None},
        })
        result = Router(task, RepoConfig()).route(
            "issues", {"action": "closed", "issue": task.issues[8],
                       "repository": {"full_name": "o/r"}})
        assert (result.role, result.issue, result.repo) == ("dispatch", "5", "")

    def test_a_marker_naming_this_repo_is_not_treated_as_cross_repo(self):
        task = task_repo(body="Part of genai-jerry/lighthouse-ui#250")
        task.issues[250] = {"number": 250, "title": "Epic", "body": "",
                            "labels": [{"name": "factory:design-approved"}],
                            "user": {"type": "User"}, "state": "open", "milestone": None}
        result = route_close(task, port_for=lambda o, r: pytest.fail("should not leave the repo"))
        assert (result.role, result.issue, result.repo) == ("dispatch", "250", "")

    def test_a_body_naming_a_different_number_does_not_redirect_the_repo(self):
        """The title's task(N) is authoritative; a stray marker cannot hijack it."""
        task = task_repo(body="Part of other/elsewhere#999")
        task.issues[250] = {"number": 250, "title": "Epic", "body": "",
                            "labels": [{"name": "factory:design-approved"}],
                            "user": {"type": "User"}, "state": "open", "milestone": None}
        result = route_close(task, port_for=lambda o, r: pytest.fail("should not leave the repo"))
        assert (result.role, result.issue, result.repo) == ("dispatch", "250", "")
