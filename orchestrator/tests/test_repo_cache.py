"""Master copies: built once, refreshed per run, copied into each workspace."""

import os
import subprocess
import threading
from pathlib import Path

from factory_orchestrator.repo_cache import RepoCache

ENV = {"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env={**ENV, "HOME": str(cwd or "/tmp")}).stdout.strip()


def commit(work: Path, name: str, content: str = "x") -> None:
    (work / name).write_text(content)
    git("add", ".", cwd=work)
    git("commit", "-qm", name, cwd=work)
    git("push", "-q", "origin", "HEAD", cwd=work)


def make_origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare 'GitHub' plus a working clone that pushes to it."""
    origin = tmp_path / "github" / "r.git"
    git("init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    git("clone", "-q", str(origin), str(work))
    git("checkout", "-q", "-b", "main", cwd=work)
    commit(work, "README.md", "hello")
    return origin, work


def make_cache(tmp_path: Path, origin: Path) -> RepoCache:
    return RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin), env=ENV)


def test_first_checkout_builds_master_and_copies_it(tmp_path):
    origin, _ = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    dest = cache.checkout("o", "r", "tok", tmp_path / "ws" / "r")

    assert (dest / "README.md").read_text() == "hello"
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=dest) == "main"
    assert git("remote", "get-url", "origin", cwd=dest) == str(origin)
    assert git("rev-parse", "origin/main", cwd=dest) == git("rev-parse", "main", cwd=origin)
    assert cache.master("o", "r").is_dir()


def test_master_holds_no_remote_url_or_fetch_head(tmp_path):
    origin, _ = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    cache.checkout("o", "r", "tok", tmp_path / "ws" / "r")
    master = cache.master("o", "r")

    # The tokenized URL is only ever passed on the command line: no remote
    # and no FETCH_HEAD means there is nowhere in the master it could be kept.
    assert git("remote", cwd=master) == ""
    assert not (master / "FETCH_HEAD").exists()
    assert str(origin) not in (master / "config").read_text()


def test_later_checkout_fetches_new_commits_into_the_same_master(tmp_path):
    origin, work = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    cache.checkout("o", "r", "tok", tmp_path / "ws1" / "r")
    marker = cache.master("o", "r") / "kept"
    marker.write_text("")

    commit(work, "NEW.md")
    dest = cache.checkout("o", "r", "tok", tmp_path / "ws2" / "r")

    assert (dest / "NEW.md").exists()
    assert marker.exists(), "master was rebuilt instead of refreshed"


def test_branches_deleted_on_origin_are_pruned(tmp_path):
    origin, work = make_origin(tmp_path)
    git("push", "-q", "origin", "HEAD:refs/heads/factory/1-spec", cwd=work)
    cache = make_cache(tmp_path, origin)
    first = cache.checkout("o", "r", "tok", tmp_path / "ws1" / "r")
    assert "origin/factory/1-spec" in git("branch", "-r", cwd=first)

    git("push", "-q", "origin", ":refs/heads/factory/1-spec", cwd=work)
    second = cache.checkout("o", "r", "tok", tmp_path / "ws2" / "r")
    assert "factory/1-spec" not in git("branch", "-r", cwd=second)


def test_default_branch_change_is_followed(tmp_path):
    origin, work = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    cache.checkout("o", "r", "tok", tmp_path / "ws1" / "r")

    git("push", "-q", "origin", "HEAD:refs/heads/trunk", cwd=work)
    git("symbolic-ref", "HEAD", "refs/heads/trunk", cwd=origin)
    dest = cache.checkout("o", "r", "tok", tmp_path / "ws2" / "r")
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=dest) == "trunk"


def test_work_in_a_copy_never_reaches_the_master(tmp_path):
    origin, _ = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    dest = cache.checkout("o", "r", "tok", tmp_path / "ws" / "r")
    git("checkout", "-q", "-b", "factory/7-task", cwd=dest)
    commit_local = dest / "change.txt"
    commit_local.write_text("y")
    git("add", ".", cwd=dest)
    git("commit", "-qm", "local", cwd=dest)

    assert "factory/7-task" not in git("branch", cwd=cache.master("o", "r"))


def test_broken_master_is_rebuilt(tmp_path):
    origin, _ = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    cache.checkout("o", "r", "tok", tmp_path / "ws1" / "r")
    master = cache.master("o", "r")
    (master / "HEAD").write_text("garbage")
    (master / "config").write_text("[[[ not a config")

    dest = cache.checkout("o", "r", "tok", tmp_path / "ws2" / "r")
    assert (dest / "README.md").read_text() == "hello"
    assert not list(master.parent.glob("*.tmp-*")), "staging dir left behind"


def test_concurrent_checkouts_of_one_repo_all_succeed(tmp_path):
    origin, _ = make_origin(tmp_path)
    cache = make_cache(tmp_path, origin)
    errors: list[BaseException] = []

    def one(i):
        try:
            cache.checkout("o", "r", "tok", tmp_path / f"ws{i}" / "r")
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all((tmp_path / f"ws{i}" / "r" / "README.md").exists() for i in range(4))
