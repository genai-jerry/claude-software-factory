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


class TestCrossRepoExpediteFanOut:
    """Expediting a cross-repo epic has to start the tasks that are not here.

    The epic sits in the coordination repo; its sub-issues sit in the repos
    that implement them, and nothing on the epic names those repos. Searching
    only the epic's own repo started the coordination repo's share and left
    every sibling repo's task parked at `factory:ready` under a marker that
    had already waived the click — the exact "stuck at approval while the epic
    is expedited" report this closes.
    """

    APPROVERS = RepoConfig(approvers={"expedite": ["boss"], "implementation": ["boss"]})

    def world(self):
        epic = FakeRepo({
            250: {"number": 250, "title": "Reorganise the list", "body": "",
                  "labels": [{"name": "factory:design-approved"},
                             {"name": "factory:expedite"}],
                  "user": {"type": "User"}, "state": "open", "milestone": None},
            265: {"number": 265, "title": "task(250): the API", "body": "",
                  "labels": [{"name": "factory:ready"}],
                  "user": {"type": "Bot"}, "state": "open", "milestone": None},
        }, {}, owner="genai-jerry", repo="lighthouse-backend")
        ui = FakeRepo({
            215: {"number": 215, "title": "task(250): the screen",
                  "body": "Part of genai-jerry/lighthouse-backend#250",
                  "labels": [{"name": "factory:ready"}],
                  "user": {"type": "Bot"}, "state": "open", "milestone": None},
        }, {}, owner="genai-jerry", repo="lighthouse-ui")
        return epic, ui

    def route(self, epic, ports, estate):
        return Router(epic, self.APPROVERS, port_for=lambda o, r: ports[f"{o}/{r}"],
                      estate=estate).route(
            "issues",
            {"action": "labeled", "issue": epic.issues[250],
             "label": {"name": "factory:expedite"},
             "sender": {"login": "boss"},
             "repository": {"full_name": "genai-jerry/lighthouse-backend"}})

    def test_it_starts_the_parked_tasks_in_every_repo_of_the_estate(self):
        epic, ui = self.world()
        ports = {"genai-jerry/lighthouse-backend": epic, "genai-jerry/lighthouse-ui": ui}
        result = self.route(epic, ports, list(ports))
        assert result.role == "implementer"
        # Index-aligned: the epic's own repo is the default, only the sibling
        # is named, and two repos could hold the same number.
        assert result.issues == ["265", "215"]
        assert result.issue_repos == ["", "genai-jerry/lighthouse-ui"]
        body = epic.comments[250][0]["body"]
        assert "genai-jerry/lighthouse-ui#215 → implementer" in body
        assert "- #265 → implementer" in body

    def test_a_single_repo_estate_is_unchanged(self):
        """No estate to search means this repo, and no per-issue repos."""
        epic, _ui = self.world()
        result = self.route(epic, {"genai-jerry/lighthouse-backend": epic}, [])
        assert (result.role, result.issues, result.issue_repos) == ("implementer", ["265"], [""])
