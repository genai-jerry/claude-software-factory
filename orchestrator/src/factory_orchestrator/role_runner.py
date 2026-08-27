"""Role execution: an isolated workspace and a headless Claude Code session.

This is the node that gives a factory role the same footing the Actions
agent job gives it, satisfying the engine contract's execution rules:

- **Workspace per run.** A fresh clone of the consuming repo in a private
  temp directory, deleted afterwards. Concurrent runs never share a
  checkout, and a global semaphore bounds how many run at once (the
  orchestrator's `max-parallel: 4` equivalent).
- **Factory files outside the workspace.** FACTORY.md and the role prompt
  are resolved from the pinned factory ref into a cache directory the agent
  cannot reach with `git add` — the same reason Actions clones the factory
  into RUNNER_TEMP rather than the workspace.
- **Same prompt, same rules.** The prompt is assembled exactly as the
  Actions engine assembles it (tests/test_role_runner.py diffs the shared
  blocks against the workflow's own heredoc), with the engine-specific
  sentences swapped: the roles are ordinary Claude Code sessions, so plugin
  skills, hooks and permission denies keep working unchanged.
- **Bounded.** `--max-turns` and a wall-clock timeout; on timeout the
  process group is killed and the outcome is reported as such.
- **Credentials by env, never in the prompt.** GH_TOKEN is the repo-scoped
  installation token (or the estate's cross-repo PAT); the Anthropic
  credential goes in as ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN. The
  transcript written for the run ledger has both redacted.
- **Observer after Claude.** When the session leaves a local `factory/*`
  (or `factory-console/*`) branch with unpushed commits, this process owns
  `commands.test`, then pushes and opens a PR. Claude's background shells
  die with `claude -p`; they are not the test runner. A red suite is never
  pushed — Claude is resumed in the same checkout (capped) to fix it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config, agent_path
from .router import AGENT_MARK, FAST_TRACK_DONE

log = logging.getLogger("factory-orchestrator.runner")

ALLOWED_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,TodoWrite,Task,Skill"

PROTECTED_BRANCHES = frozenset({"main", "master"})
FACTORY_BRANCH_PREFIXES = ("factory/", "factory-console/")
MAX_FIX_RESUMES = 2
TEST_LOG_TAIL = 8000
_PYTHON_COMMS = frozenset({"python", "python3", "pytest", "py.test"})

# The engine-neutral middle of the prompt — byte-identical to the Actions
# engine's heredoc (tests extract that heredoc from the workflow YAML and
# assert these blocks match). {role}/{repository}/{issue} are filled in.
PROMPT_BODY = """\
The factory handbook and your role instructions follow verbatim
below. Execute the role instructions, treating number
{issue} as the issue/PR argument
($ARGUMENTS).

Repo-specific facts (stack, test/build commands, conventions) live
in .factory/profile.json in the checked-out repository — your role
instructions tell you when to read it.

Operating rules:
- Use the gh CLI for GitHub operations (labels, comments, PRs); GH_TOKEN is set.
- HARD RULES: never push to main or master; never merge a pull request;
  perform exactly one factory role in this run.
- End EVERY comment you post on an issue or PR with a line containing
  exactly: <!-- factory-agent -->
  (it stops your own comments from re-triggering the pipeline).
- The pipeline puts `factory:in-progress` on your issue for the
  lifetime of this run and takes it off when the run ends. It is a
  marker, not a pipeline state: ignore it when you read the issue's
  labels, and never add or remove it yourself.

Cross-repo epics: if the change folder lists other repos in this
estate and GH_TOKEN has cross-repo access (FACTORY_CROSS_REPO_TOKEN
secret), operate on them with the gh CLI —
`gh repo clone {owner}/<repo> /tmp/<repo>` — and
create sub-issues, push factory branches and open PRs there as the role
requires (never to main/master). If the role needs cross-repo access and the
token cannot reach the other repo, comment on the epic that the
FACTORY_CROSS_REPO_TOKEN secret is required and apply factory:blocked.

"""

PROMPT_HEADER = """\
You are running the "{role}" role of the
Software Factory under the LangGraph orchestrator, on repository
{repository}.
"""

# Engine-specific: with a GitHub App installation token (or a PAT), label
# changes DO emit webhook events back into this orchestrator — the opposite
# of the Actions workflow token. The closing instruction is the same.
PROMPT_TRIGGER_NOTE = """\
Note on triggering: label changes you make DO emit events back to the
factory's orchestrator. Apply exactly the state
labels your role instructions specify — never extra ones — and let the
pipeline's own routing decide what runs next.

This is a one-shot session. When you stop calling tools the process
exits and the workspace is deleted — background shells die with it.
Never background test, build, or lint; wait for each command to
finish. Do not say you will check back later. Finish the role in this
run: the issue comment, labels, and any PR the role requires must
exist on GitHub before you stop.
"""

FIX_PROMPT = """\
You are still the "{role}" role of the Software Factory under the LangGraph
orchestrator, on repository {repository}#{issue}.

Tests failed after your last session. You are in the same checkout; the
working tree is unchanged. Fix the failures so `{test_command}` passes.

Do not background tests, build, or lint — the observer will re-run tests
after you stop. Do not push to main or master. Do not merge a pull request.
Stop when the fix is committed on the factory branch; do not start tests
yourself.

Tail of the test log:

{log_tail}
"""


def assemble_prompt(*, role: str, repository: str, owner: str, issue: int | str,
                    handbook: str, role_instructions: str) -> str:
    return (
        PROMPT_HEADER.format(role=role, repository=repository)
        + "\n"
        + PROMPT_BODY.format(issue=issue, owner=owner)
        + PROMPT_TRIGGER_NOTE
        + "\n===== FACTORY HANDBOOK =====\n\n"
        + handbook
        + f"\n\n===== ROLE INSTRUCTIONS ({role}) =====\n\n"
        + role_instructions
    )


def assemble_fix_prompt(*, role: str, repository: str, issue: int | str,
                        test_command: str, log_tail: str) -> str:
    return FIX_PROMPT.format(
        role=role, repository=repository, issue=issue,
        test_command=test_command, log_tail=log_tail)


def load_test_command(cwd: Path) -> str | None:
    """Return `.factory/profile.json` `commands.test`, or None when absent/null."""
    path = cwd / ".factory" / "profile.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    commands = data.get("commands")
    if not isinstance(commands, dict):
        return None
    cmd = commands.get("test")
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    return cmd.strip()


def inspect_pushable_branch(cwd: Path, env: dict[str, str] | None = None) -> str | None:
    """A local factory branch that is ahead of origin, or None (intake, no-op, …)."""
    current = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, env)
    if current.returncode != 0:
        return None
    branch = current.stdout.strip()
    if not branch or branch == "HEAD" or branch in PROTECTED_BRANCHES:
        return None
    if not branch.startswith(FACTORY_BRANCH_PREFIXES):
        return None
    if not _ahead_of_origin(cwd, branch, env):
        return None
    return branch


class FactorySource:
    """The factory repo at the pinned ref, cached outside every workspace."""

    def __init__(self, cfg: Config, cache_dir: str | None = None,
                 local_path: str | None = None):
        self.cfg = cfg
        self.local_path = local_path
        self.cache_dir = Path(cache_dir or tempfile.mkdtemp(prefix="factory-src-"))
        self._lock = threading.Lock()

    def _checkout(self) -> Path:
        if self.local_path:
            return Path(self.local_path)
        dest = self.cache_dir / f"factory-{self.cfg.factory_ref}"
        with self._lock:
            if not dest.exists():
                subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", self.cfg.factory_ref,
                     f"https://github.com/{self.cfg.factory_repo}", str(dest)],
                    check=True, capture_output=True, timeout=300,
                    env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/local/bin:/usr/bin:/bin"})
        return dest

    def handbook(self) -> str:
        return (self._checkout() / "FACTORY.md").read_text()

    def role_instructions(self, role: str) -> str:
        path = self._checkout() / "commands" / f"{role}.md"
        if not path.is_file():
            raise FileNotFoundError(
                f"No role definition '{role}' in {self.cfg.factory_repo}@{self.cfg.factory_ref}")
        return path.read_text()


@dataclass
class RoleOutcome:
    status: str          # success | error | timeout
    transcript: str
    exit_code: int | None = None
    error: str | None = None


class RoleRunner:
    def __init__(self, cfg: Config, source: FactorySource,
                 workspace_root: str | None = None,
                 claude_bin: str = "claude",
                 max_parallel: int | None = None):
        self.cfg = cfg
        self.source = source
        self.workspace_root = Path(workspace_root or tempfile.gettempdir())
        self.claude_bin = claude_bin
        self._slots = threading.Semaphore(max_parallel or cfg.max_parallel_default)

    def clone_workspace(self, owner: str, repo: str, token: str, dest: Path) -> None:
        log.info("clone start repo=%s/%s dest=%s", owner, repo, dest / repo)
        url = f"https://x-access-token:{token}@github.com/{owner}/{repo}"
        subprocess.run(["git", "clone", url, str(dest / repo)],
                       check=True, capture_output=True, timeout=600,
                       env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/local/bin:/usr/bin:/bin"})
        log.info("clone done repo=%s/%s dest=%s", owner, repo, dest / repo)

    def run(self, *, owner: str, repo: str, role: str, issue: int, model: str,
            github_token: str, on_phase: Callable[[str], None] | None = None) -> RoleOutcome:
        prompt = assemble_prompt(
            role=role, repository=f"{owner}/{repo}", owner=owner, issue=issue,
            handbook=self.source.handbook(),
            role_instructions=self.source.role_instructions(role))
        with self._slots:
            workspace = Path(tempfile.mkdtemp(prefix=f"run-{role}-{issue}-",
                                              dir=self.workspace_root))
            deadline = time.monotonic() + self.cfg.role_timeout_seconds
            try:
                if on_phase:
                    on_phase("cloning the repo")
                self.clone_workspace(owner, repo, github_token, workspace)
                cwd = workspace / repo
                gh_token = (self.cfg.cross_repo_token.reveal()
                            if self.cfg.cross_repo_token else github_token)
                env = {
                    "PATH": agent_path(),
                    "HOME": str(workspace),
                    "GH_TOKEN": gh_token,
                    "OPENSPEC_TELEMETRY": "0",
                    "GIT_TERMINAL_PROMPT": "0",
                    **self.cfg.agent_credential_env(),
                }
                outcome = self._invoke_claude(
                    prompt, cwd=cwd, env=env, model=model,
                    github_token=github_token, deadline=deadline,
                    on_phase=on_phase)
                if outcome.status == "timeout":
                    return outcome
                return self._observe(
                    outcome, cwd=cwd, workspace=workspace, env=env,
                    owner=owner, repo=repo, role=role, issue=issue,
                    model=model, github_token=github_token,
                    deadline=deadline, on_phase=on_phase)
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

    def _invoke_claude(self, prompt: str, *, cwd: Path, env: dict[str, str],
                       model: str, github_token: str, deadline: float,
                       on_phase: Callable[[str], None] | None) -> RoleOutcome:
        argv = [self.claude_bin, "-p", prompt,
                "--model", model,
                "--max-turns", str(self.cfg.max_turns),
                "--verbose",
                "--permission-mode", "acceptEdits",
                "--allowedTools", ALLOWED_TOOLS]
        log.info(
            "claude start role cwd=%s model=%s max_turns=%s remaining=%.0fs",
            cwd, model, self.cfg.max_turns, _remaining(deadline))
        if on_phase:
            on_phase(f"running Claude ({model})")
        try:
            proc = _run_bounded(argv, cwd=cwd, env=env, deadline=deadline)
        except subprocess.TimeoutExpired as e:
            transcript = self._redact((e.stdout or "") + "\n" + (e.stderr or ""),
                                      github_token)
            log.error("claude timeout cwd=%s after wall clock", cwd)
            return RoleOutcome(status="timeout", transcript=transcript)
        transcript = self._redact((proc.stdout or "") + "\n" + (proc.stderr or ""),
                                  github_token)
        status = "success" if proc.returncode == 0 else "error"
        log.info("claude exit cwd=%s code=%s status=%s", cwd, proc.returncode, status)
        return RoleOutcome(status=status, transcript=transcript,
                           exit_code=proc.returncode)

    def _observe(self, outcome: RoleOutcome, *, cwd: Path, workspace: Path,
                 env: dict[str, str], owner: str, repo: str, role: str,
                 issue: int, model: str, github_token: str, deadline: float,
                 on_phase: Callable[[str], None] | None) -> RoleOutcome:
        """Own tests for a local factory branch, then push — or resume Claude on red."""
        parts = [outcome.transcript]
        resumes = 0
        repository = f"{owner}/{repo}"
        last_red: RoleOutcome | None = None
        while True:
            branch = inspect_pushable_branch(cwd, env)
            if not branch:
                log.info("observer skip: no local factory branch ahead of origin")
                return last_red or outcome

            test_cmd = load_test_command(cwd)
            if test_cmd is not None:
                if on_phase:
                    on_phase("waiting for tests")
                _wait_leftover_tests(workspace, deadline)
                try:
                    test_proc, test_log = self._run_tests(test_cmd, cwd=cwd, env=env,
                                                          deadline=deadline)
                except subprocess.TimeoutExpired as e:
                    test_log = _combine(e.stdout, e.stderr)
                    parts.append("--- tests ---\n" + test_log)
                    log.error("tests timed out on %s", branch)
                    return RoleOutcome(
                        status="timeout",
                        transcript=self._redact("\n\n".join(parts), github_token),
                        error="Tests exceeded the remaining role wall clock. "
                              "The factory branch was not pushed.")
                parts.append("--- tests ---\n" + test_log)
                if test_proc.returncode != 0:
                    last_red = RoleOutcome(
                        status="error",
                        transcript=self._redact("\n\n".join(parts), github_token),
                        exit_code=test_proc.returncode,
                        error=(f"Tests failed (exit {test_proc.returncode}) on {branch}. "
                               "The factory branch was not pushed."))
                    if resumes >= MAX_FIX_RESUMES or _remaining(deadline) < 5:
                        log.error("tests failed on %s after %s fix resume(s); not pushing",
                                  branch, resumes)
                        return last_red
                    resumes += 1
                    if on_phase:
                        on_phase("fixing failing tests")
                    fix = assemble_fix_prompt(
                        role=role, repository=repository, issue=issue,
                        test_command=test_cmd, log_tail=_tail(test_log))
                    log.info("resuming Claude (%s/%s) after red tests on %s",
                             resumes, MAX_FIX_RESUMES, branch)
                    outcome = self._invoke_claude(
                        fix, cwd=cwd, env=env, model=model,
                        github_token=github_token, deadline=deadline,
                        on_phase=on_phase)
                    parts.append(outcome.transcript)
                    if outcome.status == "timeout":
                        return RoleOutcome(
                            status="timeout",
                            transcript=self._redact("\n\n".join(parts), github_token),
                            error=outcome.error)
                    continue

            if on_phase:
                on_phase("pushing the branch")
            pushed = self._push_and_open_pr(
                cwd=cwd, env=env, branch=branch, owner=owner, repo=repo,
                role=role, issue=issue, deadline=deadline)
            parts.append(pushed.transcript)
            return RoleOutcome(
                status=pushed.status,
                transcript=self._redact("\n\n".join(parts), github_token),
                exit_code=0 if pushed.status == "success" else pushed.exit_code,
                error=pushed.error)

    def _run_tests(self, test_cmd: str, *, cwd: Path, env: dict[str, str],
                   deadline: float) -> tuple[subprocess.CompletedProcess, str]:
        log.info("running commands.test remaining=%.0fs cmd=%s", _remaining(deadline), test_cmd)
        proc = _run_bounded(test_cmd, cwd=cwd, env=env, deadline=deadline, shell=True)
        return proc, _combine(proc.stdout, proc.stderr)

    def _push_and_open_pr(self, *, cwd: Path, env: dict[str, str], branch: str,
                          owner: str, repo: str, role: str, issue: int,
                          deadline: float) -> RoleOutcome:
        if branch in PROTECTED_BRANCHES or not branch.startswith(FACTORY_BRANCH_PREFIXES):
            return RoleOutcome(
                status="error", transcript="",
                error=f"Refusing to push protected or non-factory branch {branch!r}.")
        log.info("git push origin %s", branch)
        try:
            push = _run_bounded(
                ["git", "push", "-u", "origin", "HEAD"],
                cwd=cwd, env=env, deadline=deadline)
        except subprocess.TimeoutExpired as e:
            return RoleOutcome(
                status="timeout",
                transcript=_combine(e.stdout, e.stderr),
                error="git push exceeded the remaining role wall clock.")
        push_log = _combine(push.stdout, push.stderr)
        if push.returncode != 0:
            log.error("git push failed branch=%s code=%s", branch, push.returncode)
            return RoleOutcome(
                status="error", transcript=push_log, exit_code=push.returncode,
                error=f"git push of {branch} failed (exit {push.returncode}).")

        slug = f"{owner}/{repo}"
        notes = [f"--- push ---\n{push_log}"]
        pr_url = self._ensure_pr(
            cwd=cwd, env=env, slug=slug, owner=owner, branch=branch,
            issue=issue, deadline=deadline, notes=notes)
        self._ensure_trace_comment(
            cwd=cwd, env=env, slug=slug, role=role, issue=issue,
            pr_url=pr_url, deadline=deadline, notes=notes)
        return RoleOutcome(status="success", transcript="\n".join(notes))

    def _ensure_pr(self, *, cwd: Path, env: dict[str, str], slug: str, owner: str,
                   branch: str, issue: int, deadline: float, notes: list[str]) -> str:
        existing = self._gh(
            ["pr", "list", "--repo", slug, "--head", f"{owner}:{branch}",
             "--state", "open", "--json", "url,number"],
            cwd=cwd, env=env, deadline=deadline)
        notes.append(f"$ gh pr list\n{_combine(existing.stdout, existing.stderr)}")
        url = _first_pr_url(existing.stdout)
        if url:
            log.info("existing PR %s for %s", url, branch)
            return url
        title = _git(["log", "-1", "--pretty=%s"], cwd, env).stdout.strip() or branch
        base = _default_base(cwd, env)
        body = f"Closes #{issue}\n\n{AGENT_MARK}\n"
        created = self._gh(
            ["pr", "create", "--repo", slug, "--head", branch, "--base", base,
             "--title", title, "--body", body],
            cwd=cwd, env=env, deadline=deadline)
        notes.append(f"$ gh pr create\n{_combine(created.stdout, created.stderr)}")
        url = (created.stdout or "").strip().splitlines()[-1].strip() if created.stdout else ""
        if created.returncode != 0 or not url.startswith("http"):
            log.warning("gh pr create failed branch=%s code=%s", branch, created.returncode)
            return url
        log.info("opened PR %s for %s", url, branch)
        return url

    def _ensure_trace_comment(self, *, cwd: Path, env: dict[str, str], slug: str,
                              role: str, issue: int, pr_url: str, deadline: float,
                              notes: list[str]) -> None:
        listed = self._gh(
            ["api", f"repos/{slug}/issues/{issue}/comments"],
            cwd=cwd, env=env, deadline=deadline)
        notes.append(f"$ gh api comments\n{_combine(listed.stdout, listed.stderr)}")
        bodies = _comment_bodies(listed.stdout)
        if role == "fasttrack" and any(FAST_TRACK_DONE in b for b in bodies):
            return
        if pr_url and any(pr_url in b for b in bodies):
            return
        lines = [f"Opened {pr_url}" if pr_url else f"Pushed factory branch for #{issue}.", ""]
        if role == "fasttrack":
            lines.append(FAST_TRACK_DONE)
        lines.append(AGENT_MARK)
        posted = self._gh(
            ["issue", "comment", str(issue), "--repo", slug, "--body", "\n".join(lines)],
            cwd=cwd, env=env, deadline=deadline)
        notes.append(f"$ gh issue comment\n{_combine(posted.stdout, posted.stderr)}")
        if posted.returncode != 0:
            log.warning("failed to post trace comment on #%s code=%s", issue, posted.returncode)

    def _gh(self, args: list[str], *, cwd: Path, env: dict[str, str],
            deadline: float) -> subprocess.CompletedProcess:
        try:
            return _run_bounded(["gh", *args], cwd=cwd, env=env, deadline=deadline)
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(
                e.cmd, 1, e.stdout or "", e.stderr or "gh timed out")

    def _redact(self, text: str, *extra: str) -> str:
        for secret in (self.cfg.anthropic_api_key, self.cfg.claude_code_oauth_token,
                       self.cfg.cross_repo_token):
            if secret:
                text = text.replace(secret.reveal(), "***")
        for value in extra:
            if value:
                text = text.replace(value, "***")
        return text


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _run_bounded(argv: str | list[str], *, cwd: Path, env: dict[str, str],
                 deadline: float, shell: bool = False) -> subprocess.CompletedProcess:
    left = _remaining(deadline)
    if left <= 0:
        raise subprocess.TimeoutExpired(argv, 0)
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", shell=shell, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=left)
    except subprocess.TimeoutExpired as e:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(proc.args, left, output=stdout, stderr=stderr) from e
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _git(args: list[str], cwd: Path, env: dict[str, str] | None = None,
         timeout: float = 30) -> subprocess.CompletedProcess:
    git_env = {"PATH": agent_path(), "GIT_TERMINAL_PROMPT": "0", "HOME": env.get("HOME", "") if env else ""}
    if env:
        git_env.update(env)
    return subprocess.run(
        ["git", *args], cwd=cwd, env=git_env, capture_output=True, text=True,
        timeout=timeout)


def _ahead_of_origin(cwd: Path, branch: str, env: dict[str, str] | None) -> bool:
    remote = _git(["rev-parse", "--verify", "--quiet", f"origin/{branch}"], cwd, env)
    if remote.returncode == 0:
        base = f"origin/{branch}"
    else:
        head = _git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd, env)
        if head.returncode != 0 or not head.stdout.strip():
            counted = _git(["rev-list", "--count", "HEAD"], cwd, env)
            return counted.returncode == 0 and int(counted.stdout.strip() or 0) > 0
        base = head.stdout.strip()
    ahead = _git(["rev-list", "--count", f"{base}..HEAD"], cwd, env)
    if ahead.returncode != 0:
        return False
    try:
        return int(ahead.stdout.strip() or 0) > 0
    except ValueError:
        return False


def _default_base(cwd: Path, env: dict[str, str] | None) -> str:
    head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd, env)
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip().rsplit("/", 1)[-1]
    return "main"


def _wait_leftover_tests(workspace: Path, deadline: float) -> None:
    """If pytest/python whose cwd is under the workspace is still alive, wait on it."""
    pids = _workspace_python_pids(workspace)
    if not pids:
        return
    log.info("waiting on leftover test pids %s", pids)
    while pids and _remaining(deadline) > 0:
        time.sleep(min(1.0, max(0.05, _remaining(deadline))))
        pids = [p for p in pids if Path(f"/proc/{p}").exists()]


def _workspace_python_pids(workspace: Path) -> list[int]:
    procfs = Path("/proc")
    if not procfs.is_dir():
        return []
    root = workspace.resolve()
    found: list[int] = []
    for entry in procfs.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if comm not in _PYTHON_COMMS:
            continue
        try:
            cwd = (entry / "cwd").resolve()
            cwd.relative_to(root)
        except (OSError, ValueError):
            continue
        found.append(pid)
    return found


def _combine(stdout: str | None, stderr: str | None) -> str:
    return ((stdout or "") + "\n" + (stderr or "")).strip()


def _tail(text: str, limit: int = TEST_LOG_TAIL) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def _first_pr_url(raw: str) -> str:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return ""
    if isinstance(data, list) and data:
        url = data[0].get("url") if isinstance(data[0], dict) else None
        if isinstance(url, str):
            return url
    return ""


def _comment_bodies(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    bodies = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("body"), str):
            bodies.append(item["body"])
    return bodies
