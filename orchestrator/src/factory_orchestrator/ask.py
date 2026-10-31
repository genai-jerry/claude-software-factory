"""Answer a person's question about an issue's thread, with the Claude CLI.

The Console's thread view lets someone ask "why is this blocked?" or "what
does this change touch?". The Console cannot call the model itself on a
subscription login (an OAuth token authenticates the Claude CLI, not the API),
but this server already has the CLI, the agent credential and a copy of every
repo, so the question comes here.

The session is read-only: it can read files and run `git log/show/diff/blame`
in a throwaway checkout, and nothing else. No `gh`, no network tools, no
writes, no GitHub token in its environment. It counts against `MAX_PARALLEL`
like any role run, and is reported by `/usage` like one.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

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


def answer_question(engine, *, owner: str, repo: str, question: str, context: str,
                    branch: str | None = None, instructions: str | None = None) -> dict[str, Any]:
    """Run one read-only Claude session; the answer, model and usage."""
    question = (question or "").strip()
    if not question:
        raise AskError("The question is empty.", 400)
    if len(question) > MAX_QUESTION:
        raise AskError(f"The question is over {MAX_QUESTION} characters.", 400)
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
    context = (context or "")[-MAX_CONTEXT:]
    with runner._slots:  # noqa: SLF001 - an ask is a run: it shares the slots
        home = Path(tempfile.mkdtemp(prefix="ask-", dir=runner.workspace_root))
        try:
            dest = home / repo
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
                context=context or "(no comments yet)", question=question)
            argv = [runner.claude_bin, "-p", prompt, "--model", model,
                    "--max-turns", str(ASK_TURNS), "--output-format", "json",
                    "--allowedTools", ASK_TOOLS]
            env = {"PATH": agent_path(), "HOME": str(home), "OPENSPEC_TELEMETRY": "0",
                   "GIT_TERMINAL_PROMPT": "0", **cfg.agent_credential_env()}
            started = time.monotonic()
            try:
                proc = subprocess.run(argv, cwd=dest, env=env, capture_output=True,
                                      text=True, timeout=ASK_TIMEOUT)
            except subprocess.TimeoutExpired as e:
                raise AskError(f"The question took longer than {ASK_TIMEOUT} seconds.", 504) from e
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
    log.info("ask repo=%s/%s model=%s secs=%.0f turns=%s", owner, repo, model,
             time.monotonic() - started, result.get("num_turns"))
    return {"answer": answer, "model": model,
            "usage": {"input_tokens": usage.get("input_tokens", 0),
                      "output_tokens": usage.get("output_tokens", 0),
                      "cost_usd": result.get("total_cost_usd", 0)}}
