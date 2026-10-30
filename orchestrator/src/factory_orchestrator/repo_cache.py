"""Master copies of consuming repos, so a run copies from disk instead of cloning.

Each consuming repo has one bare master at `<root>/<owner>/<repo>.git`. A run
refreshes it (one incremental fetch) and then takes a local clone of it into
its own workspace — objects are hardlinked when the two share a filesystem,
copied otherwise; either way nothing crosses the network but the fetch. The
run's copy is its own repository: the agent branches, commits and pushes there,
and the workspace is deleted when the run ends. The master is never worked in.

- **No credentials at rest.** The master is built with `git init --bare` and
  fetched from an explicit URL with `--no-write-fetch-head`, so no remote URL,
  token or FETCH_HEAD is ever written into it. The run's copy gets the
  tokenized URL as `origin`, exactly as a fresh clone would.
- **One writer per repo.** A per-repo lock covers the refresh and the local
  clone, so a prune never races a copy. Different repos never wait on each
  other. Auto-gc is off so objects cannot vanish under a clone.
- **Self-healing.** A master whose refresh fails is discarded and rebuilt once;
  if the rebuild fails too, the error propagates like a failed clone.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("factory-orchestrator.repo-cache")

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/local/bin:/usr/bin:/bin"}
REFSPECS = ("+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*")


def github_url(owner: str, repo: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}"


def public_github_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


class RepoCache:
    def __init__(self, root: str | None = None,
                 url_for: Callable[[str, str, str], str] = github_url,
                 env: dict[str, str] | None = None,
                 public_url_for: Callable[[str, str], str] = public_github_url):
        self.root = Path(root or tempfile.mkdtemp(prefix="repo-cache-"))
        self.url_for = url_for
        # The token-free origin a copy is left with between runs (issue_workspaces.py).
        self.public_url_for = public_url_for
        self.env = env or GIT_ENV
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def master(self, owner: str, repo: str) -> Path:
        return self.root / owner / f"{repo}.git"

    def checkout(self, owner: str, repo: str, token: str, dest: Path) -> Path:
        """Refresh the master, then copy it to `dest` with origin on GitHub."""
        url = self.url_for(owner, repo, token)
        with self._lock(owner, repo):
            master = self._refresh(owner, repo, url)
            self._git("clone", "-q", str(master), str(dest), timeout=600)
        self._git("-C", str(dest), "remote", "set-url", "origin", url)
        return dest

    def _lock(self, owner: str, repo: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(f"{owner}/{repo}", threading.Lock())

    def _refresh(self, owner: str, repo: str, url: str) -> Path:
        master = self.master(owner, repo)
        if master.exists():
            try:
                self._fetch(master, url)
                log.info("master refreshed repo=%s/%s", owner, repo)
                return master
            except subprocess.SubprocessError:
                log.warning("master refresh failed repo=%s/%s - rebuilding", owner, repo)
                shutil.rmtree(master, ignore_errors=True)
        # Built beside its final name and renamed in, so a crash mid-fetch
        # never leaves a half-filled master that looks usable.
        master.parent.mkdir(parents=True, exist_ok=True)
        staging = master.with_name(f"{master.name}.tmp-{uuid.uuid4().hex[:8]}")
        try:
            self._git("init", "-q", "--bare", str(staging))
            self._git("-C", str(staging), "config", "gc.auto", "0")
            self._fetch(staging, url)
            staging.rename(master)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        log.info("master created repo=%s/%s path=%s", owner, repo, master)
        return master

    def _fetch(self, master: Path, url: str) -> None:
        self._git("-C", str(master), "fetch", "-q", "--prune", "--no-write-fetch-head",
                  url, *REFSPECS, timeout=600)
        # Track the remote's default branch so the run's copy checks it out.
        out = self._git("-C", str(master), "ls-remote", "--symref", url, "HEAD").stdout
        for line in out.splitlines():
            if line.startswith("ref: ") and line.endswith("\tHEAD"):
                self._git("-C", str(master), "symbolic-ref", "HEAD",
                          line[len("ref: "):-len("\tHEAD")])
                break

    def _git(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return git(self.env, *args, timeout=timeout)


def git(env: dict[str, str], *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, timeout=timeout, env=env)
