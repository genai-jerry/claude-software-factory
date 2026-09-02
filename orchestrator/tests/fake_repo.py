"""In-memory RepoPort for tests — the Python twin of makeWorld() in
scripts/test-router.js."""

from __future__ import annotations

from typing import Any


class FakeRepo:
    def __init__(self, issues: dict[int, dict[str, Any]] | None = None,
                 comments: dict[int, list[dict[str, str]]] | None = None,
                 owner: str = "o", repo: str = "r"):
        # Named, because a cross-repo estate (FACTORY.md §7) is more than one
        # of these and the searches that span it key off owner/repo.
        self.owner = owner
        self.repo = repo
        self.issues: dict[int, dict[str, Any]] = issues or {}
        self.comments: dict[int, list[dict[str, str]]] = comments or {}
        self.created: list[dict[str, Any]] = []
        self.assigned: list[tuple[int, list[str]]] = []
        self.merged_prs: list[int] = []
        # PR number -> base branch it was merged into (epic-branch routing).
        self.merged_bases: dict[int, str] = {}
        self.open_prs: dict[str, list[dict[str, Any]]] = {}
        self.branches: list[str] = ["main"]

    # -- helpers -----------------------------------------------------------
    def labels_of(self, n: int) -> list[str]:
        return [(l if isinstance(l, str) else l["name"]) for l in self.issues[n]["labels"]]

    # -- RepoPort ----------------------------------------------------------
    def list_issues(self, *, labels=None, milestone=None, state="open"):
        out = list(self.issues.values())
        if labels:
            out = [i for i in out if labels in self.labels_of(i["number"])]
        if milestone is not None:
            out = [i for i in out
                   if i.get("milestone") and str(i["milestone"]["number"]) == str(milestone)]
        if state and state != "all":
            out = [i for i in out if i.get("state", "open") == state]
        return out

    def get_issue(self, number):
        return self.issues.get(number)

    def create_issue(self, *, title, body, labels, milestone=None):
        n = max([0, *self.issues.keys()]) + 1
        iss = {"number": n, "title": title, "body": body,
               "user": {"type": "Bot"},
               "labels": [{"name": x} for x in labels],
               "milestone": {"number": milestone} if milestone else None,
               "state": "open"}
        self.issues[n] = iss
        self.created.append(iss)
        return iss

    def add_labels(self, number, labels):
        for name in labels:
            if name not in self.labels_of(number):
                self.issues[number]["labels"].append({"name": name})

    def remove_label(self, number, label):
        i = self.issues[number]
        i["labels"] = [l for l in i["labels"]
                       if (l if isinstance(l, str) else l["name"]) != label]

    def create_comment(self, number, body):
        self.comments.setdefault(number, []).append({"body": body})

    def list_comments(self, number):
        return list(self.comments.get(number, []))

    def add_assignees(self, number, assignees):
        self.assigned.append((number, assignees))

    def list_open_prs(self, head):
        return list(self.open_prs.get(head, []))

    def merge_pr(self, number, method="squash"):
        self.merged_prs.append(number)
        for prs in self.open_prs.values():
            for pr in prs:
                if pr.get("number") == number:
                    self.merged_bases[number] = (pr.get("base") or {}).get("ref", "main")

    def update_pr_base(self, number, base):
        for prs in self.open_prs.values():
            for pr in prs:
                if pr.get("number") == number:
                    pr["base"] = {"ref": base}

    def branch_exists(self, name):
        return name in self.branches

    def create_branch(self, name, from_branch):
        if name not in self.branches:
            self.branches.append(name)

    def get_file(self, path, ref=None):
        return None

    def default_branch(self):
        return "main"

    def update_issue_state(self, number, state):
        self.issues[number]["state"] = state
