"""Role execution: an isolated workspace and a headless Claude Code session.

This is the node that gives a factory role the same footing the Actions
agent job gives it, satisfying the engine contract's execution rules:

- **Workspace per run.** A copy of the repo's refreshed master
  (repo_cache.py) in a private temp directory, deleted afterwards — one
  incremental fetch instead of a full clone. A repo that opts into issue
  workspaces (issue_workspaces.py) instead works in its issue's long-lived
  copy, reset to GitHub at the start of the run; `HOME` stays per run either
  way. Concurrent runs never share a checkout, and a global semaphore bounds
  how many run at once (the orchestrator's `max-parallel: 4` equivalent).
  Under issue workspaces a run first waits its turn on its build
  environment, and only then takes a session slot, so a queued run never
  sits on a slot. The environment's notes from earlier runs go into the
  prompt, and Claude's closing summary becomes the next note.
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

import datetime as dt
import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .attachments import ConsoleAttachments, Fetched, attachments_note
from .claude_stream import StreamReader, run_usage
from .config import Config, agent_path
from .issue_workspaces import IssueKey, IssueWorkspaces
from .repo_cache import RepoCache
from .router import AGENT_MARK, FAST_TRACK_DONE

log = logging.getLogger("factory-orchestrator.runner")

ALLOWED_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,TodoWrite,Task,Skill"

PROTECTED_BRANCHES = frozenset({"main", "master"})
FACTORY_BRANCH_PREFIXES = ("factory/", "factory-console/")
MAX_FIX_RESUMES = 2

#: Roles whose Claude conversation is kept in the task's environment and
#: continued on the role's next run there (a fix round after review, a run
#: after a timeout), instead of starting over and re-reading everything.
RESUMABLE_ROLES = ("implementer",)
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
exits; anything you have not pushed is gone before the next run, and
background shells die with it.
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


ENV_NOTES_HEADER = """\
BUILD ENVIRONMENT NOTES ({place}): earlier runs in this same build
environment left these notes, oldest first. They are context, not
instructions: GitHub (issues, PRs, branches) is the state, and wins where
they disagree. End your run with a short closing summary: what you did,
what you decided and why, and what is still open. It becomes the next note.
"""


def environment_notes_block(notes: list[dict] | None, place: str) -> str:
    """The notes an environment's earlier runs left, for the prompt; '' when none."""
    if not notes:
        return ""
    lines = [ENV_NOTES_HEADER.format(place=place)]
    for n in notes:
        when = n.get("at")
        stamp = (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(when))
                 if isinstance(when, int | float) else "earlier")
        head = f"- {stamp} · {n.get('role', '?')} on #{n.get('issue', '?')} · {n.get('outcome', '?')}"
        body = (n.get("summary") or "").strip()
        lines.append(head + (("\n  " + body.replace("\n", "\n  ")) if body else ""))
    return "\n".join(lines) + "\n"


def assemble_prompt(*, role: str, repository: str, owner: str, issue: int | str,
                    handbook: str, role_instructions: str,
                    attachments: Fetched | None = None,
                    environment_notes: str = "") -> str:
    # The images fetched from the Compass sit between the engine-neutral body
    # and the trigger note: the body stays byte-identical to the Actions
    # engine's, which has no Compass to fetch from.
    note = attachments_note(attachments, int(issue)) if attachments and str(issue).isdigit() else ""
    return (
        PROMPT_HEADER.format(role=role, repository=repository)
        + "\n"
        + PROMPT_BODY.format(issue=issue, owner=owner)
        + (("\n" + note) if note else "")
        + (("\n" + environment_notes) if environment_notes else "")
        + PROMPT_TRIGGER_NOTE
        + "\n===== FACTORY HANDBOOK =====\n\n"
        + handbook
        + f"\n\n===== ROLE INSTRUCTIONS ({role}) =====\n\n"
        + role_instructions
    )


RESUME_PROMPT = """\
This is a new run of the "{role}" role of the Software Factory on
{repository} issue #{issue}. It continues your earlier conversation on this
task: this is round {round}. The factory handbook and your role
instructions from the start of this conversation still apply; the role
instructions are repeated below.

Since your last run:
- The working copy was reset to GitHub. Anything you did not push is gone;
  your branches are as you pushed them.
- Read what changed on GitHub before you act: new comments on the issue and
  on its pull request (a reviewer's findings, QA's report, a person's
  answer), and the issue's labels now. Act on where things stand now, not
  on what you remember.
"""


def assemble_resume_prompt(*, role: str, repository: str, issue: int | str, round_no: int,
                           role_instructions: str, attachments: Fetched | None = None,
                           environment_notes: str = "") -> str:
    """What a continued conversation is sent: the new run's facts, not the handbook again."""
    note = attachments_note(attachments, int(issue)) if attachments and str(issue).isdigit() else ""
    return (
        RESUME_PROMPT.format(role=role, repository=repository, issue=issue, round=round_no)
        + (("\n" + note) if note else "")
        + (("\n" + environment_notes) if environment_notes else "")
        + PROMPT_TRIGGER_NOTE
        + f"\n===== ROLE INSTRUCTIONS ({role}) =====\n\n"
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
    """The factory repo at the pinned ref, cached outside every workspace.

    Cloned once, then refreshed from the ref before a role run when the last
    fetch is older than `refresh_seconds`: the deploy workflow moves `v1` on
    every merge to main, so a prompt or handbook change reaches the roles
    without a redeploy. A failed fetch keeps the checkout it has — a flaky
    network must not turn into a failed role run.
    """

    GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/local/bin:/usr/bin:/bin"}

    def __init__(self, cfg: Config, cache_dir: str | None = None,
                 local_path: str | None = None, url: str | None = None,
                 refresh_seconds: float = 60.0):
        self.cfg = cfg
        self.local_path = local_path
        self.url = url or f"https://github.com/{cfg.factory_repo}"
        self.refresh_seconds = refresh_seconds
        self.cache_dir = Path(cache_dir or tempfile.mkdtemp(prefix="factory-src-"))
        self._lock = threading.Lock()
        self._fetched_at = 0.0

    def _checkout(self) -> Path:
        if self.local_path:
            return Path(self.local_path)
        dest = self.cache_dir / f"factory-{self.cfg.factory_ref}"
        with self._lock:
            if not dest.exists():
                subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", self.cfg.factory_ref,
                     self.url, str(dest)],
                    check=True, capture_output=True, timeout=300, env=self.GIT_ENV)
                self._fetched_at = time.monotonic()
            elif time.monotonic() - self._fetched_at >= self.refresh_seconds:
                self._refresh(dest)
        return dest

    def _refresh(self, dest: Path) -> None:
        """Move the checkout to the ref's current tip, best-effort."""
        ref = self.cfg.factory_ref
        try:
            subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", ref],
                           cwd=dest, check=True, capture_output=True, timeout=120,
                           env=self.GIT_ENV)
            subprocess.run(["git", "reset", "-q", "--hard", "FETCH_HEAD"],
                           cwd=dest, check=True, capture_output=True, timeout=60,
                           env=self.GIT_ENV)
            self._fetched_at = time.monotonic()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            err = getattr(exc, "stderr", b"") or b""
            log.warning("could not refresh the factory checkout at %s from %s@%s - keeping it: %s",
                        dest, self.url, ref, err.decode(errors="replace").strip()[:300])
            # Try again next time rather than every call.
            self._fetched_at = time.monotonic()

    def path(self) -> Path:
        """The pinned checkout itself — shared data files live beside FACTORY.md."""
        return self._checkout()

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
    #: Tokens, estimated cost and any rate-limit detail Claude reported
    #: (claude_stream.run_usage); None when it reported nothing.
    usage: dict | None = field(default=None)
    #: Claude's closing message, redacted: the environment's next note.
    summary: str | None = field(default=None)
    #: The Claude conversation the run ended in, and whether it continued
    #: an earlier one: {"resumed": bool, "round": int}; None when not kept.
    session_id: str | None = field(default=None)
    conversation: dict | None = field(default=None)


def install_branch_guard(home: Path, factory: Path | None) -> Path | None:
    """Write the settings file that wires hooks/protect-branches.py into a run.

    The plugin that ships the hook is not installed in the orchestrator's
    image, so without this nothing but the prompts stops an agent with a
    GH_TOKEN and Bash from writing to `main` or `staging`. The file goes in the
    run's private HOME and reaches Claude through `--settings`. A missing
    script wires nothing: `python3 <missing>` exits 2, which would refuse every
    call.
    """
    script = (factory / "hooks" / "protect-branches.py") if factory else None
    if script is None or not script.is_file():
        log.error("no branch guard at %s - this run is not protected", script)
        return None
    settings = home / "factory-guard-settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [{
        "matcher": "Bash|mcp__github__.*",
        "hooks": [{"type": "command", "command": f'python3 "{script}"'}],
    }]}}))
    return settings


class RoleRunner:
    def __init__(self, cfg: Config, source: FactorySource,
                 workspace_root: str | None = None,
                 claude_bin: str = "claude",
                 max_parallel: int | None = None,
                 repo_cache: RepoCache | None = None,
                 issue_workspaces: IssueWorkspaces | None = None,
                 attachments: ConsoleAttachments | None = None,
                 console_origin: Callable[[str, str], str | None] | None = None):
        self.cfg = cfg
        self.source = source
        self.workspace_root = Path(workspace_root or tempfile.gettempdir())
        self.repo_cache = repo_cache or RepoCache()
        self.issue_workspaces = issue_workspaces or IssueWorkspaces(self.repo_cache)
        self.claude_bin = claude_bin
        self._slot_total = max_parallel or cfg.max_parallel_default
        self._slots = threading.Semaphore(self._slot_total)
        # Who is in a session and who waits for one, for GET /environments.
        self._slot_guard = threading.Lock()
        self._in_session: list[dict] = []
        self._slot_queue: list[dict] = []
        # The Compass's images for the issue, fetched at run start. Both are
        # None where no Compass dispatches this orchestrator; then nothing is
        # fetched and the prompt carries no ATTACHMENTS block.
        self.attachments = attachments
        self.console_origin = console_origin

    def clone_workspace(self, owner: str, repo: str, token: str, dest: Path) -> None:
        log.info("clone start repo=%s/%s dest=%s", owner, repo, dest / repo)
        self.repo_cache.checkout(owner, repo, token, dest / repo)
        log.info("clone done repo=%s/%s dest=%s", owner, repo, dest / repo)

    def run(self, *, owner: str, repo: str, role: str, issue: int, model: str,
            github_token: str, on_phase: Callable[[str], None] | None = None,
            on_output: Callable[[str], None] | None = None,
            workspace: IssueKey | None = None,
            staging_open: bool = False,
            integration_branch: str | None = None,
            attachment_issues: list[tuple[str, int]] | None = None,
            run_id: str | None = None) -> RoleOutcome:
        """One role session. `workspace` names the issue copy to work in; None
        is a throwaway copy for this run alone. `staging_open` says a person
        approved this run writing to the integration branch (gate GS).
        `attachment_issues` names the issues whose Compass images the run
        reads (itself, and its epic for a sub-issue); None means its own."""
        who = {"run_id": run_id, "role": role, "issue": issue, "repo": f"{owner}/{repo}"}
        with self._turn(owner, repo, workspace, who, on_phase), \
                self._session_slot(owner, repo, workspace, who, on_phase):
            home = Path(tempfile.mkdtemp(prefix=f"run-{role}-{issue}-",
                                         dir=self.workspace_root))
            deadline = time.monotonic() + self.cfg.role_timeout_seconds
            try:
                if on_phase:
                    on_phase("cloning the repo")
                with self._checkout(owner, repo, github_token, home, workspace) as cwd:
                    fetched = self._fetch_attachments(
                        owner, repo, attachment_issues or [(f"{owner}/{repo}", issue)],
                        home, on_phase)
                    notes = (self.issue_workspaces.notes(owner, repo, workspace)
                             if workspace is not None else [])
                    notes_block = environment_notes_block(notes, _place(owner, repo, workspace))
                    instructions = self.source.role_instructions(role)
                    prompt = assemble_prompt(
                        role=role, repository=f"{owner}/{repo}", owner=owner, issue=issue,
                        handbook=self.source.handbook(),
                        role_instructions=instructions,
                        attachments=fetched,
                        environment_notes=notes_block)
                    keep = (workspace is not None and not workspace.staging
                            and role in RESUMABLE_ROLES)
                    name = f"{role}-{issue}"
                    kept = (self.issue_workspaces.load_conversation(
                        owner, repo, workspace, name, home) if keep else None)
                    resume = None
                    if kept:
                        resume = (kept["session_id"], assemble_resume_prompt(
                            role=role, repository=f"{owner}/{repo}", issue=issue,
                            round_no=int(kept.get("rounds") or 1) + 1,
                            role_instructions=instructions, attachments=fetched,
                            environment_notes=notes_block))
                    outcome = self._session(
                        prompt, cwd=cwd, home=home, owner=owner, repo=repo,
                        role=role, issue=issue, model=model,
                        github_token=github_token, deadline=deadline,
                        on_phase=on_phase, on_output=on_output,
                        staging_open=staging_open, integration_branch=integration_branch,
                        resume=resume)
                    if keep:
                        resumed = bool(outcome.conversation and outcome.conversation.get("resumed"))
                        rounds = (int(kept.get("rounds") or 1) + 1) if (kept and resumed) else 1
                        outcome.conversation = {"resumed": resumed, "round": rounds}
                        if outcome.status in ("success", "timeout") and outcome.session_id:
                            self.issue_workspaces.save_conversation(
                                owner, repo, workspace, name, home, outcome.session_id, rounds)
                        else:
                            # A conversation that ended in an error is not
                            # one to continue: the next run starts fresh.
                            self.issue_workspaces.drop_conversation(owner, repo, workspace, name)
                    else:
                        outcome.conversation = None
                if workspace is not None:
                    self.issue_workspaces.add_note(owner, repo, workspace, {
                        "run_id": run_id, "role": role, "issue": issue,
                        "outcome": outcome.status, "summary": outcome.summary or ""})
                return outcome
            finally:
                shutil.rmtree(home, ignore_errors=True)

    @contextmanager
    def _turn(self, owner: str, repo: str, key: IssueKey | None, who: dict,
              on_phase: Callable[[str], None] | None) -> Iterator[None]:
        """Wait for this run's build environment; a throwaway copy never waits."""
        if key is None:
            yield
            return

        def waiting() -> None:
            if on_phase:
                on_phase("waiting for its turn on staging" if key.staging
                         else "waiting for its build environment")
        with self.issue_workspaces.hold(owner, repo, key, who, on_wait=waiting):
            yield

    @contextmanager
    def _session_slot(self, owner: str, repo: str, key: IssueKey | None, who: dict,
                      on_phase: Callable[[str], None] | None) -> Iterator[None]:
        """One of the `max_parallel` Claude sessions, taken after the turn."""
        entry = {**who, "environment": (IssueWorkspaces.env_id(owner, repo, key)
                                        if key is not None else None),
                 "since": time.time()}
        if not self._slots.acquire(blocking=False):
            with self._slot_guard:
                self._slot_queue.append(entry)
            if key is not None:
                self.issue_workspaces.mark(owner, repo, key, "waiting for a session")
            if on_phase:
                on_phase("waiting for a free session")
            self._slots.acquire()
            with self._slot_guard:
                self._slot_queue = [e for e in self._slot_queue if e is not entry]
        entry = {**entry, "since": time.time()}
        with self._slot_guard:
            self._in_session.append(entry)
        if key is not None:
            self.issue_workspaces.mark(owner, repo, key, "running")
        try:
            yield
        finally:
            with self._slot_guard:
                self._in_session = [e for e in self._in_session if e is not entry]
            self._slots.release()

    def environments(self) -> dict:
        """GET /environments: the sessions in use and every build environment."""
        def public(e: dict) -> dict:
            return {"run_id": e.get("run_id"), "role": e.get("role"), "issue": e.get("issue"),
                    "repo": e.get("repo"), "environment": e.get("environment"),
                    "since": _iso_clock(e.get("since"))}
        with self._slot_guard:
            in_use = [public(e) for e in self._in_session]
            waiting = [public(e) for e in self._slot_queue]
        return {"sessions": {"total": self._slot_total, "in_use": in_use, "waiting": waiting},
                "environments": self.issue_workspaces.environments()}

    def _fetch_attachments(self, owner: str, repo: str, targets: list[tuple[str, int]],
                           home: Path, on_phase: Callable[[str], None] | None) -> Fetched:
        """The Compass's images for the run, under `home/attachments` — beside
        the checkout, never inside it. Anything that goes wrong leaves the run
        without pictures, which is what it had before."""
        if self.attachments is None or self.console_origin is None:
            return Fetched()
        origin = self.console_origin(owner, repo)
        if not origin:
            return Fetched()
        if on_phase:
            on_phase("fetching attachments")
        try:
            return self.attachments.fetch(origin, targets, home / "attachments")
        except Exception as e:  # noqa: BLE001
            log.warning("attachments: fetch failed for %s/%s: %s", owner, repo, e)
            return Fetched()

    @contextmanager
    def _checkout(self, owner: str, repo: str, token: str, home: Path,
                  key: IssueKey | None) -> Iterator[Path]:
        if key is None:
            self.clone_workspace(owner, repo, token, home)
            yield home / repo
            return
        # The turn is already held (_turn): only the reset happens here.
        with self.issue_workspaces.prepare(owner, repo, key, token) as copy:
            yield copy

    def _session(self, prompt: str, *, cwd: Path, home: Path, owner: str, repo: str,
                 role: str, issue: int, model: str, github_token: str, deadline: float,
                 on_phase: Callable[[str], None] | None,
                 on_output: Callable[[str], None] | None,
                 staging_open: bool = False,
                 integration_branch: str | None = None,
                 resume: tuple[str, str] | None = None) -> RoleOutcome:
        """`resume` is (session id, prompt): continue that conversation, or
        start afresh with `prompt` when it cannot be continued."""
        guard = install_branch_guard(home, self.source.path() if hasattr(self.source, "path") else None)
        gh_token = (self.cfg.cross_repo_token.reveal()
                    if self.cfg.cross_repo_token else github_token)
        env = {
            "PATH": agent_path(),
            "HOME": str(home),
            "GH_TOKEN": gh_token,
            "OPENSPEC_TELEMETRY": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONUNBUFFERED": "1",
            "FACTORY_STAGING_GUARD": "open" if staging_open else "closed",
            "FACTORY_INTEGRATION_BRANCH": integration_branch or "staging",
            **({"FACTORY_GUARD_SETTINGS": str(guard)} if guard else {}),
            **self.cfg.agent_credential_env(),
        }
        readers: list[StreamReader] = []
        outcome, resumed = self._invoke_continuing(
            resume[1] if resume else prompt, prompt, resume[0] if resume else None,
            cwd=cwd, env=env, model=model, github_token=github_token, deadline=deadline,
            on_phase=on_phase, on_output=on_output, readers=readers)
        if outcome.status != "timeout":
            outcome = self._observe(
                outcome, cwd=cwd, workspace=home, env=env,
                owner=owner, repo=repo, role=role, issue=issue,
                model=model, github_token=github_token,
                deadline=deadline, on_phase=on_phase, on_output=on_output,
                readers=readers)
        outcome.usage = run_usage(readers)
        outcome.summary = closing_summary(readers, lambda t: self._redact(t, github_token))
        outcome.session_id = next((r.session_id for r in reversed(readers) if r.session_id), None)
        outcome.conversation = {"resumed": resumed}
        return outcome

    def _invoke_continuing(self, resume_prompt: str, fresh_prompt: str, session_id: str | None,
                           **kw) -> tuple[RoleOutcome, bool]:
        """Continue `session_id` with `resume_prompt`; if that conversation
        will not open (the session never got going), run `fresh_prompt`."""
        readers = kw["readers"]
        if session_id:
            outcome = self._invoke_claude(resume_prompt, resume=session_id, **kw)
            started = bool(readers) and readers[-1].assistant_turns > 0
            if outcome.status != "error" or started:
                return outcome, True
            log.info("could not continue conversation %s (exit=%s) - starting fresh",
                     session_id[:12], outcome.exit_code)
        return self._invoke_claude(fresh_prompt, **kw), False

    def _invoke_claude(self, prompt: str, *, cwd: Path, env: dict[str, str],
                       model: str, github_token: str, deadline: float,
                       on_phase: Callable[[str], None] | None,
                       on_output: Callable[[str], None] | None = None,
                       readers: list[StreamReader] | None = None,
                       resume: str | None = None) -> RoleOutcome:
        # The prompt goes in on stdin, never as an argument. It carries the
        # whole handbook plus the role's instructions, and Linux caps one
        # argument at 128 KiB (MAX_ARG_STRLEN): the Release Manager's prompt
        # crossed it on 5 Nov 2026 and every release run died in execve with
        # "Argument list too long" before Claude ever started. `claude -p`
        # with no positional prompt reads it from stdin.
        argv = [self.claude_bin, "-p",
                "--model", model,
                "--max-turns", str(self.cfg.max_turns),
                # JSON events so the run's usage can be read (claude_stream);
                # the log still shows text. stream-json requires --verbose.
                "--output-format", "stream-json",
                "--verbose",
                "--permission-mode", "acceptEdits",
                "--allowedTools", ALLOWED_TOOLS]
        if env.get("FACTORY_GUARD_SETTINGS"):
            argv += ["--settings", env["FACTORY_GUARD_SETTINGS"]]
        if resume:
            argv += ["--resume", resume]
        log.info(
            "claude start role cwd=%s model=%s max_turns=%s remaining=%.0fs",
            cwd, model, self.cfg.max_turns, _remaining(deadline))
        if on_phase:
            on_phase(f"running Claude ({model})"
                     + (", continuing its earlier conversation" if resume else ""))
        emit = self._emitter(github_token, on_output)
        reader = StreamReader()
        if readers is not None:
            readers.append(reader)

        def show(line: str) -> None:
            text = reader.feed(line)
            if text and emit:
                emit(text)

        try:
            proc = _run_bounded(argv, cwd=cwd, env=env, deadline=deadline,
                                on_output=show, stdin=prompt)
        except subprocess.TimeoutExpired:
            log.error("claude timeout cwd=%s after wall clock", cwd)
            return RoleOutcome(status="timeout",
                               transcript=self._redact(reader.text(), github_token))
        transcript = self._redact(reader.text(), github_token)
        status = "success" if proc.returncode == 0 else "error"
        log.info("claude exit cwd=%s code=%s status=%s", cwd, proc.returncode, status)
        return RoleOutcome(status=status, transcript=transcript,
                           exit_code=proc.returncode)

    def _observe(self, outcome: RoleOutcome, *, cwd: Path, workspace: Path,
                 env: dict[str, str], owner: str, repo: str, role: str,
                 issue: int, model: str, github_token: str, deadline: float,
                 on_phase: Callable[[str], None] | None,
                 on_output: Callable[[str], None] | None = None,
                 readers: list[StreamReader] | None = None) -> RoleOutcome:
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
                _wait_leftover_tests((workspace, cwd), deadline)
                try:
                    test_proc, test_log = self._run_tests(
                        test_cmd, cwd=cwd, env=env, deadline=deadline,
                        github_token=github_token, on_output=on_output)
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
                    # Continue the conversation that wrote the code, so it
                    # fixes with what it knows; a fresh one if that fails.
                    current = next((r.session_id for r in reversed(readers or [])
                                    if r.session_id), None)
                    outcome, _ = self._invoke_continuing(
                        fix, fix, current, cwd=cwd, env=env, model=model,
                        github_token=github_token, deadline=deadline,
                        on_phase=on_phase, on_output=on_output,
                        readers=readers if readers is not None else [])
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
                   deadline: float, github_token: str = "",
                   on_output: Callable[[str], None] | None = None,
                   ) -> tuple[subprocess.CompletedProcess, str]:
        log.info("running commands.test remaining=%.0fs cmd=%s", _remaining(deadline), test_cmd)
        emit = self._emitter(github_token, on_output)
        proc = _run_bounded(test_cmd, cwd=cwd, env=env, deadline=deadline,
                            shell=True, on_output=emit)
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

    def _emitter(self, github_token: str,
                 on_output: Callable[[str], None] | None) -> Callable[[str], None] | None:
        if on_output is None:
            return None

        def emit(text: str) -> None:
            on_output(self._redact(text, github_token))

        return emit

    def _redact(self, text: str, *extra: str) -> str:
        for secret in (self.cfg.anthropic_api_key, self.cfg.claude_code_oauth_token,
                       self.cfg.cross_repo_token):
            if secret:
                text = text.replace(secret.reveal(), "***")
        for value in extra:
            if value:
                text = text.replace(value, "***")
        return text


def closing_summary(readers: list[StreamReader], redact: Callable[[str], str]) -> str | None:
    """Claude's last closing message across the run's sessions (a fix resume
    speaks last), redacted; None when it sent none."""
    for reader in reversed(readers):
        for result in reversed(reader.results):
            body = result.get("result")
            if isinstance(body, str) and body.strip():
                return redact(body.strip())
    return None


def _place(owner: str, repo: str, key: IssueKey | None) -> str:
    if key is None:
        return "this run only"
    if key.staging:
        return f"{owner}/{repo} staging environment"
    return f"the environment of {owner}/{repo}#{key.number}"


def _iso_clock(epoch: object) -> str | None:
    if not isinstance(epoch, int | float):
        return None
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat()


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _run_bounded(argv: str | list[str], *, cwd: Path, env: dict[str, str],
                 deadline: float, shell: bool = False,
                 on_output: Callable[[str], None] | None = None,
                 stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run a process, forwarding stdout/stderr as they arrive so the Console
    can show Claude and test output before the process exits. `stdin`, when
    given, is written to the process and closed — on its own thread, so a
    child that fills its stdout pipe before reading its stdin cannot deadlock
    against the writer."""
    left = _remaining(deadline)
    if left <= 0:
        raise subprocess.TimeoutExpired(argv, 0)
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        text=True, errors="replace", bufsize=1, shell=shell, start_new_session=True)
    chunks: list[str] = []
    q: queue.Queue[str | None] = queue.Queue()

    if stdin is not None:
        def feed() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(stdin)
                proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                # The child exited (or never read): its exit code tells the
                # story, and the pump below still collects what it said.
                pass

        threading.Thread(target=feed, daemon=True).start()

    def pump() -> None:
        try:
            assert proc.stdout is not None
            while True:
                line = proc.stdout.readline()
                if line == "":
                    break
                q.put(line)
        finally:
            q.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    try:
        while True:
            left = _remaining(deadline)
            if left <= 0:
                timed_out = True
                _kill_group(proc)
                break
            try:
                item = q.get(timeout=min(0.5, max(0.05, left)))
            except queue.Empty:
                continue
            if item is None:
                break
            chunks.append(item)
            if on_output:
                on_output(item)
    finally:
        if timed_out:
            while True:
                try:
                    item = q.get(timeout=0.2)
                except queue.Empty:
                    break
                if item is None:
                    break
                chunks.append(item)
                if on_output:
                    on_output(item)
        reader.join(timeout=2)
        if proc.poll() is None:
            _kill_group(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    stdout = "".join(chunks)
    if timed_out:
        raise subprocess.TimeoutExpired(proc.args, max(0.0, left), output=stdout, stderr="")
    code = proc.returncode if proc.returncode is not None else -1
    return subprocess.CompletedProcess(proc.args, code, stdout, "")


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


def _wait_leftover_tests(roots: tuple[Path, ...], deadline: float) -> None:
    """If pytest/python whose cwd is under the run's HOME or checkout is still alive, wait on it."""
    pids = sorted({p for root in roots for p in _workspace_python_pids(root)})
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
