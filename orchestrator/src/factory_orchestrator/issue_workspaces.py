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

Each copy is a **build environment** with three levels (6 Nov 2026):

- **Staging, one per repo** (`<root>/<owner>/<repo>/staging/repo`). Every
  Release Manager run that writes to the integration branch works here, so
  epics go onto staging one at a time, in the order they asked. Never swept.
- **Epic.** The epic's own roles, plus a task's Release Manager merging the
  task into the epic branch, so merges into one epic take turns.
- **Task.** Implementer, reviewer and QA for that task.

One run at a time per environment: :meth:`hold` is the turn, and it is
taken *before* a session slot (role_runner.py), so a run waiting its turn
holds no slot. :meth:`environments` reports who holds each turn and who is
queued for it, for GET /environments. Each environment keeps `notes.jsonl`
beside its copy (never in it, so the reset cannot touch them): one entry per
run, which the next run there reads before it starts.
"""

from __future__ import annotations

import datetime as dt
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
#: Notes kept per environment, and how much of them a prompt carries.
NOTES_KEPT = 40
NOTES_IN_PROMPT = 6
NOTE_SUMMARY_CHARS = 1500
#: A builder's conversation is continued on its next run while it is this
#: young, has been continued fewer times than this, and is no bigger than
#: this; past any of them the next run starts fresh.
CONVERSATION_MAX_AGE = 3 * 86400
CONVERSATION_MAX_ROUNDS = 6
CONVERSATION_MAX_BYTES = 40 * 1024 * 1024
#: The commit that carries a run's uncommitted edits into its bundle; undone
#: (reset --mixed) when the work is restored, so the edits come back unstaged.
WIP_COMMIT_MESSAGE = "factory: unfinished work, not pushed"

_SUB_ISSUE_TITLE = re.compile(r"^(?:task|test|bug)\((\d+)\)")
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)",
                     re.IGNORECASE)


@dataclass(frozen=True)
class IssueKey:
    """Which copy a run uses: the issue's own number, and the epic it belongs to."""

    number: int
    epic: str | None = None      # "owner/repo#n", or None for an epic or a standalone issue
    staging: bool = False        # the repo's one staging environment; `number` is unused

    def label(self) -> str:
        """Who waits on whom, in words: `staging`, `epic`, or `issue`."""
        return "staging" if self.staging else ("task" if self.epic else "issue")


STAGING = IssueKey(0, None, True)


def _iso(epoch: float | None) -> str | None:
    if not isinstance(epoch, int | float):
        return None
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat()


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
        #: Live turns, by environment id: who holds it, who is queued.
        self._holders: dict[str, dict[str, Any]] = {}
        self._queues: dict[str, list[dict[str, Any]]] = {}

    def path(self, owner: str, repo: str, number: int | str) -> Path:
        return self.root / owner / repo / str(number)

    def home(self, owner: str, repo: str, key: IssueKey) -> Path:
        return self.path(owner, repo, "staging" if key.staging else key.number)

    @staticmethod
    def env_id(owner: str, repo: str, key: IssueKey) -> str:
        return f"{owner}/{repo}@staging" if key.staging else f"{owner}/{repo}#{key.number}"

    @contextmanager
    def acquire(self, owner: str, repo: str, key: IssueKey, token: str) -> Iterator[Path]:
        """The issue's copy, reset to GitHub, for the length of one run."""
        with self.hold(owner, repo, key):
            with self.prepare(owner, repo, key, token) as copy:
                yield copy

    @contextmanager
    def hold(self, owner: str, repo: str, key: IssueKey, who: dict[str, Any] | None = None,
             on_wait: Callable[[], None] | None = None) -> Iterator[None]:
        """This environment's turn: one run at a time, first come first served.

        `who` (run id, role, issue) is what GET /environments shows; `on_wait`
        is called once if the turn is not free at once.
        """
        env = self.env_id(owner, repo, key)
        lock = self._key_lock(env)
        entry = {**(who or {}), "since": self.clock()}
        if not lock.acquire(blocking=False):
            with self._guard:
                self._queues.setdefault(env, []).append(entry)
            if on_wait:
                on_wait()
            lock.acquire()
            with self._guard:
                waiting = [w for w in self._queues.get(env, []) if w is not entry]
                if waiting:
                    self._queues[env] = waiting
                else:
                    self._queues.pop(env, None)
        try:
            with self._guard:
                self._holders[env] = {**entry, "since": self.clock(), "state": "starting"}
            yield
        finally:
            with self._guard:
                self._holders.pop(env, None)
            lock.release()

    def mark(self, owner: str, repo: str, key: IssueKey, state: str) -> None:
        """Say what the run holding this environment is doing (`waiting for a
        session`, `running`)."""
        env = self.env_id(owner, repo, key)
        with self._guard:
            if env in self._holders:
                self._holders[env]["state"] = state

    @contextmanager
    def prepare(self, owner: str, repo: str, key: IssueKey, token: str) -> Iterator[Path]:
        """The copy, reset to GitHub. The caller already holds the turn."""
        home = self.home(owner, repo, key)
        copy = home / "repo"
        url = self.cache.url_for(owner, repo, token)
        if copy.exists():
            try:
                self._reset(copy, url)
                log.info("issue copy reused %s", self.env_id(owner, repo, key))
            except subprocess.SubprocessError:
                log.warning("issue copy could not be reset %s - recopying",
                            self.env_id(owner, repo, key))
                shutil.rmtree(copy, ignore_errors=True)
        if not copy.exists():
            home.mkdir(parents=True, exist_ok=True)
            self.cache.checkout(owner, repo, token, copy)
            log.info("issue copy created %s", self.env_id(owner, repo, key))
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
            if meta.get("staging"):
                continue  # the repo's staging environment is never swept
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

    # ------------------------------------------------------------- notes
    def add_note(self, owner: str, repo: str, key: IssueKey, entry: dict[str, Any]) -> None:
        """Append one run's entry to the environment's notes; keep the latest few."""
        home = self.home(owner, repo, key)
        path = home / "notes.jsonl"
        try:
            home.mkdir(parents=True, exist_ok=True)
            kept = self._read_notes(path)[-(NOTES_KEPT - 1):]
            summary = str(entry.get("summary") or "").strip()
            if len(summary) > NOTE_SUMMARY_CHARS:
                summary = summary[:NOTE_SUMMARY_CHARS].rstrip() + " …"
            kept.append({**entry, "summary": summary, "at": self.clock()})
            path.write_text("".join(json.dumps(n) + "\n" for n in kept))
        except OSError:
            log.warning("could not write notes for %s", self.env_id(owner, repo, key),
                        exc_info=True)

    def notes(self, owner: str, repo: str, key: IssueKey,
              limit: int = NOTES_IN_PROMPT) -> list[dict[str, Any]]:
        """The environment's latest notes, oldest first."""
        return self._read_notes(self.home(owner, repo, key) / "notes.jsonl")[-limit:]

    @staticmethod
    def _read_notes(path: Path) -> list[dict[str, Any]]:
        try:
            lines = path.read_text().splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                note = json.loads(line)
            except ValueError:
                continue
            if isinstance(note, dict):
                out.append(note)
        return out

    # ------------------------------------------------------- conversations
    def save_conversation(self, owner: str, repo: str, key: IssueKey, name: str,
                          run_home: Path, session_id: str, rounds: int) -> bool:
        """Keep a run's Claude conversation beside the copy, to continue later.

        Claude writes it under the run's private HOME, which is deleted when
        the run ends; the file is copied out with its path relative to that
        HOME, so the next run can put it back where `--resume` looks.
        """
        found = next(iter(run_home.glob(f".claude/projects/*/{session_id}.jsonl")), None)
        if found is None:
            log.info("no conversation file for %s in %s", session_id, run_home)
            return False
        dest = self.home(owner, repo, key) / "conversations" / name
        try:
            shutil.rmtree(dest, ignore_errors=True)
            rel = found.relative_to(run_home)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, dest / rel)
            (dest / "conversation.json").write_text(json.dumps({
                "session_id": session_id, "path": str(rel), "rounds": rounds,
                "saved_at": self.clock(), "bytes": found.stat().st_size}))
            return True
        except OSError:
            log.warning("could not keep conversation %s", session_id, exc_info=True)
            shutil.rmtree(dest, ignore_errors=True)
            return False

    def load_conversation(self, owner: str, repo: str, key: IssueKey, name: str,
                          run_home: Path) -> dict[str, Any] | None:
        """Put a kept conversation into a new run's HOME; its record, or None
        when there is none worth continuing (too old, too long, too big)."""
        src = self.home(owner, repo, key) / "conversations" / name
        try:
            meta = json.loads((src / "conversation.json").read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(meta, dict) or not isinstance(meta.get("session_id"), str):
            return None
        stale = self.clock() - float(meta.get("saved_at") or 0) > CONVERSATION_MAX_AGE
        if (stale or int(meta.get("rounds") or 0) >= CONVERSATION_MAX_ROUNDS
                or int(meta.get("bytes") or 0) > CONVERSATION_MAX_BYTES):
            self.drop_conversation(owner, repo, key, name)
            return None
        rel = Path(str(meta.get("path") or ""))
        if rel.is_absolute() or ".." in rel.parts or not (src / rel).is_file():
            self.drop_conversation(owner, repo, key, name)
            return None
        try:
            (run_home / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, run_home / rel)
        except OSError:
            return None
        return meta

    def drop_conversation(self, owner: str, repo: str, key: IssueKey, name: str) -> None:
        shutil.rmtree(self.home(owner, repo, key) / "conversations" / name, ignore_errors=True)

    # ---------------------------------------------------- unfinished work
    def save_wip(self, owner: str, repo: str, key: IssueKey, copy: Path,
                 run_id: str | None = None) -> dict[str, Any] | None:
        """Keep what a run did but never pushed, beside the copy.

        The next run resets the copy to GitHub, which is right for state and
        wrong for half-finished work: a task too big for one run then starts
        from nothing every time. The work on the run's `factory/<task>`
        branch — its local commits and its uncommitted edits — goes into a
        git bundle beside the copy, and :meth:`restore_wip` puts it back
        after the next reset. Returns the record, or None when there was
        nothing to keep.
        """
        def g(*args: str) -> str:
            return git(self.cache.env, "-C", str(copy), *args, timeout=120).stdout.strip()

        self.drop_wip(owner, repo, key)
        try:
            branch = g("symbolic-ref", "--quiet", "--short", "HEAD")
        except subprocess.SubprocessError:
            return None  # detached: nothing branch-shaped to keep
        if not branch.startswith("factory/") or branch.startswith("factory/epic-"):
            return None
        try:
            wip_commit = False
            if g("status", "--porcelain"):
                g("add", "-A")
                g("-c", "user.name=factory", "-c", "user.email=factory@localhost",
                  "commit", "-q", "--no-verify", "-m", WIP_COMMIT_MESSAGE)
                wip_commit = True
            ahead = int(g("rev-list", "--count", branch, "--not", "--remotes") or 0)
            if ahead == 0:
                return None
            dest = self.home(owner, repo, key) / "wip"
            dest.mkdir(parents=True, exist_ok=True)
            g("bundle", "create", str(dest / "work.bundle"), branch, "--not", "--remotes")
            meta = {"branch": branch, "head": g("rev-parse", branch),
                    "commits": ahead - (1 if wip_commit else 0), "uncommitted": wip_commit,
                    "saved_at": self.clock(), "run_id": run_id}
            (dest / "wip.json").write_text(json.dumps(meta))
            log.info("kept unfinished work on %s for %s (%d commit(s)%s)", branch,
                     self.env_id(owner, repo, key), meta["commits"],
                     " + edits" if wip_commit else "")
            return meta
        except (subprocess.SubprocessError, OSError, ValueError):
            log.warning("could not keep unfinished work for %s",
                        self.env_id(owner, repo, key), exc_info=True)
            self.drop_wip(owner, repo, key)
            return None

    def restore_wip(self, owner: str, repo: str, key: IssueKey, copy: Path) -> dict[str, Any] | None:
        """Put kept unfinished work back into a freshly reset copy.

        Skipped (and the work dropped) when it is too old, or when GitHub
        moved the branch on in a way the kept work does not build on: then
        GitHub wins, as everywhere else.
        """
        src = self.home(owner, repo, key) / "wip"
        try:
            meta = json.loads((src / "wip.json").read_text())
        except (OSError, ValueError):
            return None
        branch = meta.get("branch") if isinstance(meta, dict) else None
        if (not isinstance(branch, str) or not branch.startswith("factory/")
                or self.clock() - float(meta.get("saved_at") or 0) > CONVERSATION_MAX_AGE):
            self.drop_wip(owner, repo, key)
            return None

        def g(*args: str) -> subprocess.CompletedProcess:
            return git(self.cache.env, "-C", str(copy), *args, timeout=120)

        temp = f"refs/factory-wip/{branch}"
        try:
            g("fetch", "-q", str(src / "work.bundle"), f"+refs/heads/{branch}:{temp}")
            on_github = f"refs/remotes/origin/{branch}"
            exists = subprocess.run(["git", "-C", str(copy), "rev-parse", "--verify", "-q",
                                     on_github], env=self.cache.env, capture_output=True)
            if exists.returncode == 0:
                ancestor = subprocess.run(
                    ["git", "-C", str(copy), "merge-base", "--is-ancestor", on_github, temp],
                    env=self.cache.env, capture_output=True)
                if ancestor.returncode != 0:
                    log.info("GitHub moved %s on; dropping the kept work", branch)
                    self.drop_wip(owner, repo, key)
                    return None
            g("checkout", "-q", "-f", "-B", branch, temp)
            if meta.get("uncommitted"):
                g("reset", "-q", "--mixed", "HEAD~1")
            return meta
        except subprocess.SubprocessError:
            log.warning("could not restore unfinished work on %s - starting from GitHub",
                        branch, exc_info=True)
            self.drop_wip(owner, repo, key)
            return None
        finally:
            subprocess.run(["git", "-C", str(copy), "update-ref", "-d", temp],
                           env=self.cache.env, capture_output=True)

    def drop_wip(self, owner: str, repo: str, key: IssueKey) -> None:
        shutil.rmtree(self.home(owner, repo, key) / "wip", ignore_errors=True)

    # ------------------------------------------------------- environments
    def environments(self, notes: int = 5) -> list[dict[str, Any]]:
        """Every environment on disk, with who holds it and who waits for it.

        `kind` is `staging`, `epic` (an issue some task copy names as its
        epic), `task`, or `issue` (standalone). An environment a run is
        waiting for that has never been created is listed too.
        """
        copies = list(self._copies())
        epics = {meta.get("epic") for _, meta in copies if meta.get("epic")}
        with self._guard:
            holders = {k: dict(v) for k, v in self._holders.items()}
            queues = {k: [dict(w) for w in v] for k, v in self._queues.items()}
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for home, meta in copies:
            owner, repo = meta.get("owner"), meta.get("repo")
            if not (owner and repo):
                continue
            staging = bool(meta.get("staging"))
            number = meta.get("number")
            env = f"{owner}/{repo}@staging" if staging else f"{owner}/{repo}#{number}"
            seen.add(env)
            kind = ("staging" if staging else "epic" if meta.get("ref") in epics
                    else "task" if meta.get("epic") else "issue")
            out.append({
                "id": env, "kind": kind, "repo": f"{owner}/{repo}",
                "number": None if staging else number, "epic": meta.get("epic"),
                "created_at": _iso(meta.get("created_at")),
                "last_used_at": _iso(meta.get("last_used_at")),
                "active": self._public_turn(holders.get(env)),
                "queue": [self._public_turn(w) for w in queues.get(env, [])],
                "notes": [self._public_note(n) for n in
                          self._read_notes(home / "notes.jsonl")[-notes:]][::-1],
            })
        for env in sorted({*holders, *queues} - seen):
            repo_part, _, rest = env.partition("@") if "@" in env else env.partition("#")
            staging = env.endswith("@staging")
            out.append({
                "id": env, "kind": "staging" if staging else "issue", "repo": repo_part,
                "number": None if staging else int(rest) if rest.isdigit() else None,
                "epic": None, "created_at": None, "last_used_at": None,
                "active": self._public_turn(holders.get(env)),
                "queue": [self._public_turn(w) for w in queues.get(env, [])],
                "notes": [],
            })
        return out

    @staticmethod
    def _public_turn(turn: dict[str, Any] | None) -> dict[str, Any] | None:
        if not turn:
            return None
        return {"run_id": turn.get("run_id"), "role": turn.get("role"),
                "issue": turn.get("issue"), "state": turn.get("state", "waiting"),
                "since": _iso(turn.get("since"))}

    @staticmethod
    def _public_note(note: dict[str, Any]) -> dict[str, Any]:
        return {"at": _iso(note.get("at")), "role": note.get("role"),
                "issue": note.get("issue"), "run_id": note.get("run_id"),
                "outcome": note.get("outcome"), "summary": note.get("summary") or ""}

    # ------------------------------------------------------------ internals
    def _key_lock(self, env: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(env, threading.Lock())

    def _lock(self, owner: str, repo: str, number: int) -> threading.Lock:
        return self._key_lock(f"{owner}/{repo}#{number}")

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
        if key.staging:
            meta.update({"owner": owner, "repo": repo, "number": None, "staging": True,
                         "ref": self.env_id(owner, repo, key), "epic": None,
                         "last_used_at": self.clock()})
        else:
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
