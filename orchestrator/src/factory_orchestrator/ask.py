"""Answer a person's question about an issue's thread, with the Claude CLI.

The Console's thread view lets someone ask "why is this blocked?" or "what
does this change touch?". The Console cannot call the model itself on a
subscription login (an OAuth token authenticates the Claude CLI, not the API),
but this server already has the CLI, the agent credential and a copy of every
repo, so the question comes here.

The session is read-only: it can read files and run `git log/show/diff/blame`
in a throwaway checkout, and nothing else. No `gh`, no network tools, no
writes, no GitHub token in its environment. It counts against `MAX_PARALLEL`
like any role run, and is recorded in the run ledger as a finished `ask` run
so `/usage` counts what it spent.

Two modes. `ask` answers a question about a thread. `shape` is the Compass's
Shape page: a longer conversation that turns an idea into a requirement, so
its budgets are wider. Either may carry image attachments — screenshots the
person uploaded — which are written beside the checkout and named in the
prompt for the Read tool, which views images.

A conversation may keep its workspace between messages (`conversation`): the
home under `<workspace_root>/ask/<key>` survives, each message brings every
copy level with GitHub (fetch from the mirror, detach, reset, clean) instead
of cloning again, and the Claude session can be resumed (`session`) so the
model keeps what it already read and only the new question is sent. Idle
conversation homes are pruned after a day.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .claude_stream import TOKEN_KEYS
from .config import agent_path
from .models import ModelResolutionError, load_models_config, resolve_model
from .reconcile import usage_limit_error

log = logging.getLogger("factory-orchestrator.ask")

ASK_TOOLS = ("Read,Grep,Glob,Bash(git log:*),Bash(git show:*),Bash(git diff:*),"
             "Bash(git blame:*),Bash(git ls-files:*),Bash(git branch:*)")
MAX_QUESTION = 2_000
MAX_CONTEXT = 24_000
ASK_TIMEOUT = 300
ASK_TURNS = 14

#: Per-mode budgets: (max question chars, max context chars, turns, seconds).
#: `shape` is a conversation that is shaping work, not answering a question,
#: so it may say more, remember more, and read more of the repo.
MODES: dict[str, tuple[int, int, int, int]] = {
    "ask": (MAX_QUESTION, MAX_CONTEXT, ASK_TURNS, ASK_TIMEOUT),
    "shape": (12_000, 60_000, 24, 480),
}

#: Image attachments: what the Read tool can view, how many, how large.
IMAGE_MIMES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

#: Sibling repositories a conversation may read beside the primary one.
MAX_REPOS = 8

#: A persistent conversation workspace: its key, and how long it may sit idle.
CONVERSATION_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ASK_IDLE_SECONDS = 24 * 3600
_conv_guard = threading.Lock()
_conv_locks: dict[str, threading.Lock] = {}


def _conv_lock(key: str) -> threading.Lock:
    with _conv_guard:
        return _conv_locks.setdefault(key, threading.Lock())


def prune_conversations(workspace_root: Path, now: float | None = None) -> int:
    """Delete conversation homes idle longer than ASK_IDLE_SECONDS; how many went.

    A home in use is skipped (its lock is held), so a long answer is never
    pulled from under the session. Cheap: one listdir and a stat each, run
    at the start of every ask.
    """
    base = Path(workspace_root) / "ask"
    if not base.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - ASK_IDLE_SECONDS
    gone = 0
    for home in base.iterdir():
        try:
            if not home.is_dir() or home.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        lock = _conv_lock(home.name)
        if not lock.acquire(blocking=False):
            continue
        try:
            shutil.rmtree(home, ignore_errors=True)
            gone += 1
        finally:
            lock.release()
    if gone:
        log.info("ask: pruned %s idle conversation workspace(s)", gone)
    return gone

INTRO = """You answer a question from a person using the Compass.

Repository: {repo}. Your working directory is a read-only checkout of it{branch_note}.
You can read files and run `git log`, `git show`, `git diff` and `git blame`.
You cannot change anything, and you cannot reach GitHub or any other service.{siblings}"""

#: How to write the answer, unless the caller (the Console, which sends the
#: same standard plus its citation rules) brings its own.
DEFAULT_INSTRUCTIONS = """Writing standard (every answer; FACTORY.md §1a):
- Start with the answer, in one sentence of 15 words or fewer.
- If the reader must do something, add one line: "**You need to:** <one action>".
  If nothing is needed, leave the line out.
- Then at most 5 bullets: only facts that change what the reader does or decides.
  Use a list for 3 or more items. A paragraph has 4 sentences or fewer.
- Keep the whole answer to 120 words, or 150 if the question asks for detail.
- One sentence, one idea. An instruction has 20 words or fewer; any other
  sentence has 25 or fewer. Use the active voice. Use the command form for
  what the reader must do.
- Use one word for one thing: always "task", "epic", "test case", "bug".
- Name a gate by what it does, then its code: "design approval (G2)".
- Write a label or a config key only when the reader must type it. Do not
  explain how the factory works. Do not describe how you decided.
- Write an issue or PR as #21, or owner/repo#21 in another repo.
- If the thread and the code do not answer the question, say what is missing.
  Do not guess."""

PROMPT = """{intro}

{instructions}
{attachments}
What you are given (oldest first; the factory's own comments are marked [agent]):

{context}

The question:

{question}
"""
MAX_INSTRUCTIONS = 8_000

#: What a resumed session is sent: the new question and its attachments. The
#: repositories, the instructions and the earlier turns are what it remembers.
RESUME_PROMPT = """{attachments}{question}
"""


class AskError(RuntimeError):
    """A question that cannot be answered, with the reason to show the asker."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=120, env={"PATH": agent_path(), "GIT_TERMINAL_PROMPT": "0"})


def _result_of(stdout: str) -> dict[str, Any] | None:
    """The CLI's JSON result: the last line that is a JSON object with a result."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and ("result" in obj or obj.get("type") == "result"):
                return obj
    return None


def check_images(images: Any) -> list[dict[str, Any]]:
    """Validate the `images` a caller sent; the decoded files, or an AskError (400).

    Done once, before anything is cloned: a bad upload must not cost a slot.
    """
    if images is None:
        return []
    if not isinstance(images, list):
        raise AskError("images must be a list.", 400)
    if len(images) > MAX_IMAGES:
        raise AskError(f"At most {MAX_IMAGES} images per message.", 400)
    out: list[dict[str, Any]] = []
    for i, img in enumerate(images, start=1):
        if not isinstance(img, dict):
            raise AskError(f"Image {i} is not an object.", 400)
        mime = str(img.get("mime") or "").lower()
        if mime not in IMAGE_MIMES:
            raise AskError(f"Image {i}: {mime or 'no type'} is not supported. Use PNG, JPEG, GIF or WebP.", 400)
        try:
            data = base64.b64decode(str(img.get("data_b64") or ""), validate=True)
        except (binascii.Error, ValueError) as e:
            raise AskError(f"Image {i} is not valid base64.", 400) from e
        if not data:
            raise AskError(f"Image {i} is empty.", 400)
        if len(data) > MAX_IMAGE_BYTES:
            raise AskError(f"Image {i} is over 5 MB.", 400)
        stem = _SAFE_NAME.sub("-", Path(str(img.get("name") or "image")).stem).strip("-.") or "image"
        out.append({"name": f"{i}-{stem[:60]}.{IMAGE_MIMES[mime]}", "mime": mime, "data": data})
    return out


def check_repos(repos: Any, owner: str, repo: str) -> list[dict[str, Any]]:
    """Validate the sibling `repos` a caller sent; the list to check out, or an AskError (400).

    An entry naming the primary repository is dropped: it is already there.
    """
    if repos is None:
        return []
    if not isinstance(repos, list):
        raise AskError("repos must be a list.", 400)
    if len(repos) > MAX_REPOS:
        raise AskError(f"At most {MAX_REPOS} repositories per question.", 400)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, r in enumerate(repos, start=1):
        if not isinstance(r, dict):
            raise AskError(f"Repository {i} is not an object.", 400)
        o, n = r.get("owner"), r.get("repo")
        if not isinstance(o, str) or not o.strip() or not isinstance(n, str) or not n.strip():
            raise AskError(f"Repository {i} needs owner and repo.", 400)
        b = r.get("branch")
        if b is not None and not isinstance(b, str):
            raise AskError(f"Repository {i}: branch must be a string or null.", 400)
        o, n = o.strip(), n.strip()
        key = f"{o}/{n}".lower()
        if key == f"{owner}/{repo}".lower() or key in seen or n == repo:
            continue  # the primary, a duplicate, or a name that would collide with the primary's folder
        seen.add(key)
        out.append({"owner": o, "repo": n, "branch": (b or "").strip() or None})
    return out


def _checkout_on(dest: Path, branch: str | None) -> str:
    """Detach `dest` on `branch` when the remote has it; the branch actually checked out."""
    if branch and _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                       dest).returncode == 0:
        if _git(["checkout", "-q", "--detach", f"origin/{branch}"], dest).returncode == 0:
            return branch
    head = _git(["rev-parse", "--abbrev-ref", "HEAD"], dest)
    name = (head.stdout or "").strip()
    return name if name and name != "HEAD" else "the default branch"


def _default_label(dest: Path) -> str:
    head = _git(["rev-parse", "--abbrev-ref", "HEAD"], dest)
    name = (head.stdout or "").strip()
    return name if name and name != "HEAD" else "the default branch"


def _level(engine, owner: str, name: str, token: str, dest: Path, branch: str | None) -> str:
    """Bring an existing copy level with GitHub through the mirror; the branch it sits on.

    The copy has no remote (none may carry a token), so the fetch names the
    mirror's path with an explicit refspec, then the copy is detached on the
    wanted branch and reset hard. Only ignored files survive between messages.
    """
    cache = engine.runner.repo_cache
    master = cache.refresh_master(owner, name, token)
    fetched = _git(["fetch", "-q", "--prune", "--no-write-fetch-head", str(master),
                    "+refs/heads/*:refs/remotes/origin/*"], dest)
    if fetched.returncode != 0:
        raise RuntimeError(f"fetch from the mirror failed: {fetched.stderr.strip()[-200:]}")
    default = cache.default_branch(owner, name)
    on = branch if branch and _git(["rev-parse", "--verify", "--quiet",
                                    f"refs/remotes/origin/{branch}"], dest).returncode == 0 else default
    for args in (["checkout", "-q", "--detach", f"origin/{on}"], ["reset", "-q", "--hard"],
                 ["clean", "-q", "-fd"]):
        done = _git(args, dest)
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {done.stderr.strip()[-200:]}")
    return on


def _prepare_repo(engine, home: Path, owner: str, name: str, token: str,
                  branch: str | None) -> tuple[Path, str]:
    """A read-only copy of owner/name under home, on branch when it exists.

    A copy left by an earlier message is levelled rather than cloned; one that
    cannot be levelled is thrown away and cloned afresh. Either way no token
    survives in it: a fresh clone loses its remote right after the checkout.
    """
    dest = home / name
    if (dest / ".git").exists():
        try:
            return dest, _level(engine, owner, name, token, dest, branch)
        except Exception as e:  # noqa: BLE001 - throwaway on doubt, like issue copies
            log.warning("ask: copy of %s/%s could not be levelled (%s) - recloning", owner, name, e)
            shutil.rmtree(dest, ignore_errors=True)
    engine.runner.repo_cache.checkout(owner, name, token, dest)
    on = _checkout_on(dest, branch)
    _git(["remote", "remove", "origin"], dest)
    return dest, on


def _checkout_siblings(engine, home: Path, siblings: list[dict[str, Any]],
                       tokens: list[str]) -> list[dict[str, Any]]:
    """Put each sibling beside the primary; what landed and what did not.

    A sibling the engine cannot reach — no installation, a failed clone — is
    reported in the prompt as unavailable and never fails the question: the
    primary repository still answers most of it.
    """
    out = []
    for sib in siblings:
        o, n = sib["owner"], sib["repo"]
        dest = home / n
        try:
            token = engine.app.installation_token(o, n, min_remaining=600)
            tokens.append(token)
            dest, on = _prepare_repo(engine, home, o, n, token, sib.get("branch"))
            out.append({"name": n, "path": dest, "branch": on, "ok": True})
        except Exception as e:  # noqa: BLE001 - one sibling must not fail the ask
            log.warning("ask: sibling %s/%s unavailable: %s", o, n, e)
            shutil.rmtree(dest, ignore_errors=True)
            out.append({"name": n, "path": dest, "branch": None, "ok": False})
    return out


def _siblings_note(siblings: list[dict[str, Any]]) -> str:
    if not siblings:
        return ""
    there = [f"`../{s['name']}` (on `{s['branch']}`)" for s in siblings if s["ok"]]
    gone = [f"`{s['name']}`" for s in siblings if not s["ok"]]
    lines = []
    if there:
        lines.append("\nOther repositories of this project are checked out beside it, read-only: "
                     + ", ".join(there) + ". Read them when the question crosses repositories.")
    if gone:
        lines.append("\nNot available this time (say so if the question needs them): " + ", ".join(gone) + ".")
    return "".join(lines)


def _write_images(home: Path, images: list[dict[str, Any]]) -> list[Path]:
    """Put the attachments beside (never inside) the checkout; their paths."""
    folder = home / "attachments"
    shutil.rmtree(folder, ignore_errors=True)  # last message's files: already read
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for img in images:
        path = folder / img["name"]
        path.write_bytes(img["data"])
        paths.append(path)
    return paths


def _attachments_note(paths: list[Path]) -> str:
    if not paths:
        return ""
    n = len(paths)
    lines = "\n".join(f"- {p}" for p in paths)
    return (f"\nThe person attached {n} image{'s' if n != 1 else ''}. Read each one with the Read "
            f"tool before answering:\n{lines}\n")


def _record_usage(engine, *, owner: str, repo: str, mode: str, model: str,
                  result: dict[str, Any]) -> None:
    """Enter the ask in the run ledger as a finished run, so /usage counts it.

    Started and finished in one go: it never appears as a live run (it has
    no issue), but its tokens and cost sit beside the role runs'. A ledger
    that cannot be written must not fail an answer already in hand.
    """
    ledger = getattr(engine, "ledger", None)
    if ledger is None:
        return
    usage = result.get("usage") or {}
    try:
        run_id = ledger.start_run(repo=f"{owner}/{repo}", issue=0, role="ask", trigger=mode)
        ledger.finish_run(run_id, outcome="success", model=model, guards={"usage": {
            **{k: int(usage.get(k) or 0) for k in TOKEN_KEYS},
            "turns": int(result.get("num_turns") or 0),
            "cost_usd": float(result.get("total_cost_usd") or 0),
        }})
    except Exception:  # noqa: BLE001 - bookkeeping, never the answer
        log.warning("ask: could not record usage in the ledger", exc_info=True)


def answer_question(engine, *, owner: str, repo: str, question: str, context: str,
                    branch: str | None = None, instructions: str | None = None,
                    images: list[dict[str, Any]] | None = None,
                    mode: str = "ask",
                    repos: list[dict[str, Any]] | None = None,
                    conversation: str | None = None,
                    session: str | None = None) -> dict[str, Any]:
    """Run one read-only Claude session; the answer, model, usage and session.

    With `conversation` the workspace is kept between calls and brought level
    with GitHub each time; with `session` too, the earlier Claude session is
    resumed and only the new question is sent. A resume that fails falls back
    to a fresh prompt with whatever `context` the caller sent.
    """
    if mode not in MODES:
        raise AskError(f"Unknown mode {mode!r}; use ask or shape.", 400)
    if conversation is not None and not CONVERSATION_KEY.match(conversation):
        raise AskError("conversation must match [A-Za-z0-9_-]{1,64}.", 400)
    if session is not None and (not isinstance(session, str) or not session.strip()
                                or len(session) > 128):
        raise AskError("session must be a short string.", 400)
    max_question, max_context, turns, timeout = MODES[mode]
    question = (question or "").strip()
    if not question:
        raise AskError("The question is empty.", 400)
    if len(question) > max_question:
        raise AskError(f"The question is over {max_question} characters.", 400)
    files = check_images(images)
    wanted = check_repos(repos, owner, repo)
    cfg, runner = engine.cfg, engine.runner
    if not cfg.agent_credential_env():
        raise AskError("The factory has no Claude credential to answer with. Store "
                       "CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in the Console's "
                       "settings.", 503)
    port = engine.port(owner, repo)
    try:
        model = resolve_model("ask", load_models_config(port), engine.probe).model
    except ModelResolutionError as e:
        raise AskError(str(e), 503) from e

    token = engine.app.installation_token(owner, repo, min_remaining=600)
    tokens = [token]  # every token that touched this home, for redaction
    context = (context or "")[-max_context:]
    persistent = conversation is not None
    root = Path(runner.workspace_root)
    if persistent:
        prune_conversations(root)
        (root / "ask").mkdir(parents=True, exist_ok=True)
    conv_lock = _conv_lock(conversation) if persistent else nullcontext()
    resumed = False
    with conv_lock, runner._slots:  # noqa: SLF001 - an ask is a run: it shares the slots
        if persistent:
            home = root / "ask" / conversation
            existed = home.is_dir()
            home.mkdir(exist_ok=True)
        else:
            home = Path(tempfile.mkdtemp(prefix="ask-", dir=runner.workspace_root))
            existed = False
        try:
            attached = _write_images(home, files)
            dest, on = _prepare_repo(engine, home, owner, repo, token, branch)
            on_branch = bool(branch) and on == branch
            siblings = _checkout_siblings(engine, home, wanted, tokens)
            common = ["--model", model, "--max-turns", str(turns), "--output-format", "json",
                      "--allowedTools", ASK_TOOLS]
            # The tools reach only the working directory unless told
            # otherwise; each sibling is granted explicitly, nothing else.
            for sib in siblings:
                if sib["ok"]:
                    common += ["--add-dir", str(sib["path"])]
            env = {"PATH": agent_path(), "HOME": str(home), "OPENSPEC_TELEMETRY": "0",
                   "GIT_TERMINAL_PROMPT": "0", **cfg.agent_credential_env()}
            started = time.monotonic()

            # The prompt goes in on stdin, as the roles' do (role_runner):
            # Linux caps one argument at 128 KiB, and a prompt that carries a
            # whole thread and its documents can cross it.
            def run(argv: list[str], prompt_text: str) -> subprocess.CompletedProcess:
                try:
                    return subprocess.run(argv, cwd=dest, env=env, capture_output=True,
                                          text=True, timeout=timeout, input=prompt_text)
                except subprocess.TimeoutExpired as e:
                    raise AskError(f"The question took longer than {timeout} seconds.", 504) from e

            proc = None
            if persistent and session and existed:
                # The session remembers the repositories, the instructions
                # and the earlier turns; it is sent the new question alone.
                short = RESUME_PROMPT.format(attachments=_attachments_note(attached), question=question)
                proc = run([runner.claude_bin, "-p", "--resume", session.strip(), *common], short)
                got = _result_of(proc.stdout or "")
                if proc.returncode == 0 and got and not got.get("is_error") and str(got.get("result") or "").strip():
                    resumed = True
                else:
                    log.info("ask: resume of %s failed (exit=%s) - starting fresh", session[:12], proc.returncode)
            if not resumed:
                prompt = PROMPT.format(
                    intro=INTRO.format(repo=f"{owner}/{repo}",
                                       branch_note=f", on `{branch}`" if on_branch else "",
                                       siblings=_siblings_note(siblings)),
                    instructions=(instructions or "").strip()[:MAX_INSTRUCTIONS] or DEFAULT_INSTRUCTIONS,
                    attachments=_attachments_note(attached),
                    context=context or "(no comments yet)", question=question)
                proc = run([runner.claude_bin, "-p", *common], prompt)
        finally:
            if persistent:
                try:
                    os.utime(home, None)  # idle time counts from the last message
                except OSError:
                    pass
            else:
                shutil.rmtree(home, ignore_errors=True)

    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for t in tokens:
        raw = runner._redact(raw, t)  # noqa: SLF001
    limit = usage_limit_error(raw)
    if limit:
        raise AskError(limit, 429)
    result = _result_of(proc.stdout or "")
    if result is None:
        log.warning("ask: unreadable output exit=%s tail=%r", proc.returncode, raw[-300:])
        raise AskError("Claude did not return an answer.")
    answer = str(result.get("result") or "").strip()
    for t in tokens:
        answer = runner._redact(answer, t)  # noqa: SLF001
    if proc.returncode != 0 or result.get("is_error") or not answer:
        raise AskError(answer or "Claude did not return an answer.")
    usage = result.get("usage") or {}
    log.info("ask repo=%s/%s mode=%s model=%s images=%s siblings=%s secs=%.0f turns=%s", owner,
             repo, mode, model, len(files), sum(1 for x in siblings if x["ok"]),
             time.monotonic() - started, result.get("num_turns"))
    _record_usage(engine, owner=owner, repo=repo, mode=mode, model=model, result=result)
    return {"answer": answer, "model": model,
            "session": result.get("session_id"), "resumed": resumed,
            "usage": {"input_tokens": usage.get("input_tokens", 0),
                      "output_tokens": usage.get("output_tokens", 0),
                      "cost_usd": result.get("total_cost_usd", 0)}}
