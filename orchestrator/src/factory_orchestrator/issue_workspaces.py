"""Copies of a consuming repo that live for a whole issue, not a single run.

Opt-in per repo (`runners.workspace: "issue"` in .github/factory-orchestrator.json).
Under it, every run on the same issue works in the same copy at
`<root>/<owner>/<repo>/<number>/repo`, so what git ignores — node_modules,
.venv, build output, test caches — stays warm from the implementer through
review, QA and every fix run.

- **The unit is the issue.** An epic's own roles share the epic's copy; each
  task sub-issue gets its own, because tasks under one epic run at the same
  time and one working tree has one checked-out branch. A run handed a PR
  number (reviewer, QA) works in the copy of the task the PR closes.
- **Flat names.** Issue and PR numbers come from one counter per repo, so
  `<repo>/<number>` cannot collide. The epic a task belongs to is recorded in
  the copy's `meta.json` instead of in its path: a cross-repo task's path
  would otherwise name an epic that is not in that repo.
- **A cache, never state.** GitHub is the state machine, and the Actions
  engine keeps nothing between runs, so neither may this one. Every run
  starts by forcing the copy to what is on GitHub: tracked changes, stashes,
  half-finished merges and local-only branches are dropped, every local
  branch is reset to its origin counterpart. Only ignored files survive.
- **No token at rest.** `origin` carries the run's token while the run is
  live and the token-free URL between runs.
- **Throwaway on doubt.** A copy that cannot be reset is deleted and copied
  afresh from the repo master (repo_cache.py) — always safe, because it was
  only ever a cache.
- **Lifetime.** Deleted when its issue closes (an epic closing takes its
  tasks' copies with it), or by the reconciler sweep when the issue is found
  closed or the copy has sat idle for `idle_days`.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .repo_cache import RepoCache, git
from .router import epic_ref_from_body

log = logging.getLogger("factory-orchestrator.issue-workspaces")

MODES = ("run", "issue")
DEFAULT_IDLE_DAYS = 7.0

_SUB_ISSUE_TITLE = re.compile(r"^(?:task|test|bug)\((\d+)\)")
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)",
                     re.IGNORECASE)


@dataclass(frozen=True)
class IssueKey:
    """Which copy a run uses: the issue's own number, and the epic it belongs to."""

    number: int
    epic: str | None = None      # "owner/repo#n", or None for an epic or a standalone issue


def workspace_key(port, number: int) -> IssueKey:
    """Resolve the number a role was handed to the issue whose copy it works in.

    A PR resolves to the task it closes (`Closes #N` — every implementer PR
    carries one); a PR that names none keeps its own number and gets a cold
    copy, which is slower but still correct.
    """
    issue = port.get_issue(number) or {}
    if issue.get("pull_request") is not None:
        m = _CLOSES.search(issue.get("body") or "")
        if not m:
            return IssueKey(number)
        number = int(m.group(1))
        issue = port.get_issue(number) or {}
    m = _SUB_ISSUE_TITLE.match(issue.get("title") or "")
    if not m:
        return IssueKey(number)
    epic = int(m.group(1))
    epic_repo, body_number = epic_ref_from_body(issue.get("body"))
    if epic_repo is None or body_number != epic:
        epic_repo = f"{port.owner}/{port.repo}"
    return IssueKey(number, f"{epic_repo}#{epic}")


class IssueWorkspaces:
    def __init__(self, cache: RepoCache, root: str | None = None,
                 idle_days: float = DEFAULT_IDLE_DAYS,
                 clock: Callable[[], float] = time.time):
        self.cache = cache
        self.root = Path(root or tempfile.mkdtemp(prefix="issue-workspaces-"))
        self.idle_days = idle_days
        self.clock = clock
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def path(self, owner: str, repo: str, number: int) -> Path:
        return self.root / owner / repo / str(number)

    @contextmanager
    def acquire(self, owner: str, repo: str, key: IssueKey, token: str) -> Iterator[Path]:
        """The issue's copy, reset to GitHub, for the length of one run."""
        home = self.path(owner, repo, key.number)
        copy = home / "repo"
        url = self.cache.url_for(owner, repo, token)
        with self._lock(owner, repo, key.number):
            if copy.exists():
                try:
                    self._reset(copy, url)
                    log.info("issue copy reused repo=%s/%s#%s", owner, repo, key.number)
                except subprocess.SubprocessError:
                    log.warning("issue copy could not be reset repo=%s/%s#%s - recopying",
                                owner, repo, key.number)
                    shutil.rmtree(copy, ignore_errors=True)
            if not copy.exists():
                home.mkdir(parents=True, exist_ok=True)
                self.cache.checkout(owner, repo, token, copy)
                log.info("issue copy created repo=%s/%s#%s", owner, repo, key.number)
            self._write_meta(home, owner, repo, key)
            try:
                yield copy
            finally:
                try:
                    git(self.cache.env, "-C", str(copy), "remote", "set-url", "origin",
                        self.cache.public_url_for(owner, repo))
                except (subprocess.SubprocessError, OSError):
                    # A copy that will not take the token-free URL is not kept.
                    shutil.rmtree(copy, ignore_errors=True)
                self._touch(home)

    def discard(self, owner: str, repo: str, number: int) -> int:
        """Delete an issue's copy and, for an epic, every copy that names it.

        Never waits: this runs on the delivery worker, and a copy still in use
        by a run is left for the sweep, which finds its issue closed.
        """
        ref = f"{owner}/{repo}#{number}"
        removed = 0
        for home, meta in self._copies():
            if meta.get("ref") == ref or meta.get("epic") == ref:
                removed += self._remove(home, meta)
        if removed:
            log.info("discarded %d issue cop%s for %s", removed,
                     "y" if removed == 1 else "ies", ref)
        return removed

    def sweep(self, is_closed: Callable[[str, str, int], bool]) -> int:
        """Delete copies whose issue is closed or that have sat idle too long.

        A copy in use is skipped, never waited on; the next pass gets it.
        """
        removed = 0
        cutoff = self.clock() - self.idle_days * 86400
        for home, meta in self._copies():
            owner, repo, number = meta.get("owner"), meta.get("repo"), meta.get("number")
            if not (owner and repo and isinstance(number, int)):
                removed += self._remove(home, meta)
                continue
            try:
                stale = float(meta.get("last_used_at", 0)) < cutoff
                if not stale and not is_closed(owner, repo, number):
                    continue
            except Exception:  # noqa: BLE001 - a failed lookup keeps the copy
                log.warning("could not check %s/%s#%s - keeping its copy",
                            owner, repo, number, exc_info=True)
                continue
            removed += self._remove(home, meta)
        return removed

    # ------------------------------------------------------------ internals
    def _lock(self, owner: str, repo: str, number: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(f"{owner}/{repo}#{number}", threading.Lock())

    def _remove(self, home: Path, meta: dict[str, Any]) -> int:
        owner, repo, number = meta.get("owner"), meta.get("repo"), meta.get("number")
        lock = (self._lock(owner, repo, number)
                if owner and repo and isinstance(number, int) else threading.Lock())
        if not lock.acquire(blocking=False):
            return 0
        try:
            shutil.rmtree(home, ignore_errors=True)
            return 1
        finally:
            lock.release()

    def _copies(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        for meta_path in sorted(self.root.glob("*/*/*/meta.json")):
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, ValueError):
                meta = {}
            yield meta_path.parent, meta if isinstance(meta, dict) else {}

    def _write_meta(self, home: Path, owner: str, repo: str, key: IssueKey) -> None:
        meta_path = home / "meta.json"
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            meta = {"created_at": self.clock()}
        meta.update({"owner": owner, "repo": repo, "number": key.number,
                     "ref": f"{owner}/{repo}#{key.number}", "epic": key.epic,
                     "last_used_at": self.clock()})
        meta_path.write_text(json.dumps(meta, indent=2))

    def _touch(self, home: Path) -> None:
        meta_path = home / "meta.json"
        try:
            meta = json.loads(meta_path.read_text())
            meta["last_used_at"] = self.clock()
            meta_path.write_text(json.dumps(meta, indent=2))
        except (OSError, ValueError):
            pass

    def _reset(self, copy: Path, url: str) -> None:
        """Force the copy to GitHub's state; keep only what git ignores."""
        def g(*args: str, timeout: int = 120) -> str:
            return git(self.cache.env, "-C", str(copy), *args, timeout=timeout).stdout

        dot_git = copy / ".git"
        # What a run killed mid-command leaves behind.
        (dot_git / "index.lock").unlink(missing_ok=True)
        for leftover in ("rebase-merge", "rebase-apply"):
            shutil.rmtree(dot_git / leftover, ignore_errors=True)
        for leftover in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            (dot_git / leftover).unlink(missing_ok=True)

        g("remote", "set-url", "origin", url)
        g("fetch", "-q", "--prune", "--tags", "--force", "origin", timeout=600)
        g("remote", "set-head", "origin", "--auto")
        default = g("symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        default_branch = default.removeprefix("origin/")

        g("reset", "-q", "--hard")
        g("clean", "-q", "-fd")          # no -x: ignored files are the point
        g("stash", "clear")
        g("checkout", "-q", "-f", "-B", default_branch, default)
        remote = set(g("for-each-ref", "--format=%(refname:short)",
                       "refs/remotes/origin/").split())
        for branch in g("for-each-ref", "--format=%(refname:short)",
                        "refs/heads/").split():
            if branch == default_branch:
                continue
            if f"origin/{branch}" in remote:
                g("branch", "-q", "-f", branch, f"origin/{branch}")
            else:
                g("branch", "-q", "-D", branch)
