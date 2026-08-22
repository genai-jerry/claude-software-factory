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
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import Config

log = logging.getLogger("factory-orchestrator.runner")

ALLOWED_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,TodoWrite,Task,Skill"

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
        url = f"https://x-access-token:{token}@github.com/{owner}/{repo}"
        subprocess.run(["git", "clone", url, str(dest / repo)],
                       check=True, capture_output=True, timeout=600,
                       env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/local/bin:/usr/bin:/bin"})

    def run(self, *, owner: str, repo: str, role: str, issue: int, model: str,
            github_token: str) -> RoleOutcome:
        prompt = assemble_prompt(
            role=role, repository=f"{owner}/{repo}", owner=owner, issue=issue,
            handbook=self.source.handbook(),
            role_instructions=self.source.role_instructions(role))
        with self._slots:
            workspace = Path(tempfile.mkdtemp(prefix=f"run-{role}-{issue}-",
                                              dir=self.workspace_root))
            try:
                self.clone_workspace(owner, repo, github_token, workspace)
                cwd = workspace / repo
                gh_token = (self.cfg.cross_repo_token.reveal()
                            if self.cfg.cross_repo_token else github_token)
                env = {
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": str(workspace),
                    "GH_TOKEN": gh_token,
                    "OPENSPEC_TELEMETRY": "0",
                }
                if self.cfg.anthropic_api_key:
                    env["ANTHROPIC_API_KEY"] = self.cfg.anthropic_api_key.reveal()
                if self.cfg.claude_code_oauth_token:
                    env["CLAUDE_CODE_OAUTH_TOKEN"] = self.cfg.claude_code_oauth_token.reveal()
                argv = [self.claude_bin, "-p", prompt,
                        "--model", model,
                        "--max-turns", str(self.cfg.max_turns),
                        "--permission-mode", "acceptEdits",
                        "--allowedTools", ALLOWED_TOOLS]
                try:
                    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                          text=True, timeout=self.cfg.role_timeout_seconds)
                except subprocess.TimeoutExpired as e:
                    transcript = self._redact((e.stdout or "") + "\n" + (e.stderr or ""),
                                              github_token)
                    log.error("role %s on %s/%s#%s timed out", role, owner, repo, issue)
                    return RoleOutcome(status="timeout", transcript=transcript)
                transcript = self._redact(proc.stdout + "\n" + proc.stderr, github_token)
                status = "success" if proc.returncode == 0 else "error"
                return RoleOutcome(status=status, transcript=transcript,
                                   exit_code=proc.returncode)
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

    def _redact(self, text: str, *extra: str) -> str:
        for secret in (self.cfg.anthropic_api_key, self.cfg.claude_code_oauth_token,
                       self.cfg.cross_repo_token):
            if secret:
                text = text.replace(secret.reveal(), "***")
        for value in extra:
            if value:
                text = text.replace(value, "***")
        return text
