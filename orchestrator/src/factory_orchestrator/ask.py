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
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import subprocess
import tempfile
import time
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

INTRO = """You answer a question from a person using the Compass.

Repository: {repo}. Your working directory is a read-only checkout of it{branch_note}.
You can read files and run `git log`, `git show`, `git diff` and `git blame`.
You cannot change anything, and you cannot reach GitHub or any other service."""

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


def _write_images(home: Path, images: list[dict[str, Any]]) -> list[Path]:
    """Put the attachments beside (never inside) the checkout; their paths."""
    folder = home / "attachments"
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
                    mode: str = "ask") -> dict[str, Any]:
    """Run one read-only Claude session; the answer, model and usage."""
    if mode not in MODES:
        raise AskError(f"Unknown mode {mode!r}; use ask or shape.", 400)
    max_question, max_context, turns, timeout = MODES[mode]
    question = (question or "").strip()
    if not question:
        raise AskError("The question is empty.", 400)
    if len(question) > max_question:
        raise AskError(f"The question is over {max_question} characters.", 400)
    files = check_images(images)
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
    context = (context or "")[-max_context:]
    with runner._slots:  # noqa: SLF001 - an ask is a run: it shares the slots
        home = Path(tempfile.mkdtemp(prefix="ask-", dir=runner.workspace_root))
        try:
            dest = home / repo
            attached = _write_images(home, files)
            runner.repo_cache.checkout(owner, repo, token, dest)
            on_branch = False
            if branch and _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                               dest).returncode == 0:
                on_branch = _git(["checkout", "-q", "--detach", f"origin/{branch}"], dest).returncode == 0
            # No token may outlive the clone: the session cannot push or call
            # GitHub. (After the checkout: removing the remote drops its branches.)
            _git(["remote", "remove", "origin"], dest)
            prompt = PROMPT.format(
                intro=INTRO.format(repo=f"{owner}/{repo}",
                                   branch_note=f", on `{branch}`" if on_branch else ""),
                instructions=(instructions or "").strip()[:MAX_INSTRUCTIONS] or DEFAULT_INSTRUCTIONS,
                attachments=_attachments_note(attached),
                context=context or "(no comments yet)", question=question)
            argv = [runner.claude_bin, "-p", prompt, "--model", model,
                    "--max-turns", str(turns), "--output-format", "json",
                    "--allowedTools", ASK_TOOLS]
            env = {"PATH": agent_path(), "HOME": str(home), "OPENSPEC_TELEMETRY": "0",
                   "GIT_TERMINAL_PROMPT": "0", **cfg.agent_credential_env()}
            started = time.monotonic()
            try:
                proc = subprocess.run(argv, cwd=dest, env=env, capture_output=True,
                                      text=True, timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise AskError(f"The question took longer than {timeout} seconds.", 504) from e
        finally:
            import shutil
            shutil.rmtree(home, ignore_errors=True)

    raw = runner._redact((proc.stdout or "") + "\n" + (proc.stderr or ""), token)  # noqa: SLF001
    limit = usage_limit_error(raw)
    if limit:
        raise AskError(limit, 429)
    result = _result_of(proc.stdout or "")
    if result is None:
        log.warning("ask: unreadable output exit=%s tail=%r", proc.returncode, raw[-300:])
        raise AskError("Claude did not return an answer.")
    answer = runner._redact(str(result.get("result") or "").strip(), token)  # noqa: SLF001
    if proc.returncode != 0 or result.get("is_error") or not answer:
        raise AskError(answer or "Claude did not return an answer.")
    usage = result.get("usage") or {}
    log.info("ask repo=%s/%s mode=%s model=%s images=%s secs=%.0f turns=%s", owner, repo, mode,
             model, len(files), time.monotonic() - started, result.get("num_turns"))
    _record_usage(engine, owner=owner, repo=repo, mode=mode, model=model, result=result)
    return {"answer": answer, "model": model,
            "usage": {"input_tokens": usage.get("input_tokens", 0),
                      "output_tokens": usage.get("output_tokens", 0),
                      "cost_usd": result.get("total_cost_usd", 0)}}
