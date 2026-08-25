"""Orchestrator configuration.

Everything comes from the environment (12-factor: the container is configured
by its deployment, never by files inside the image). Secrets are held in
`Secret` wrappers so neither `repr()` nor structured logging can leak them —
the run ledger and transcripts must never contain credentials
(orchestration/langgraph-engine spec).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


class ConfigError(ValueError):
    """A required setting is missing or invalid."""


# scripts/dev.sh fills these so the process can boot before a real token
# arrives from the Console store or a /dispatch. They must not win over
# those sources, and they must not be handed to Claude.
DEV_PLACEHOLDERS = frozenset({"sk-dev-placeholder", "dev-placeholder"})


def is_usable_credential(value: str) -> bool:
    v = (value or "").strip()
    return bool(v) and v not in DEV_PLACEHOLDERS


def agent_path() -> str:
    """PATH for the Claude CLI. Keep the process PATH so a local install
    (e.g. ~/.local/bin/claude) is visible; fall back to the usual bins."""
    return os.environ.get("PATH") or "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"


class Secret:
    """A string that refuses to print itself."""

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def usable(self) -> bool:
        return is_usable_credential(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Secret(****)"

    __str__ = __repr__


@dataclass
class Config:
    """Validated orchestrator settings."""

    # GitHub App identity (how the orchestrator authenticates to GitHub).
    github_app_id: str
    github_app_private_key: Secret
    github_webhook_secret: Secret
    # Anthropic credential for role runs. Optional at boot: Console forwards
    # a token on POST /events, or CONSOLE_DATABASE_URL fills these later.
    anthropic_api_key: Secret
    claude_code_oauth_token: Secret
    # Where execution bookkeeping lives. sqlite:///... or postgresql+psycopg://...
    database_url: str = "sqlite:///factory-orchestrator.db"
    # The factory repo supplying FACTORY.md + role prompts, and the pinned ref.
    factory_repo: str = "genai-jerry/claude-software-factory"
    factory_ref: str = "v1"
    # This engine's name as consuming repos declare it in factory-orchestrator.json.
    engine_name: str = "langgraph"
    # GitHub API endpoint (override for GHES).
    github_api_url: str = "https://api.github.com"
    # Execution budgets — mirror the Actions engine's caps.
    max_parallel_default: int = 4
    role_timeout_seconds: int = 45 * 60
    max_turns: int = 100
    # Public base URL of this service; failure comments link run logs under it.
    public_base_url: str = "http://localhost:8080"
    # Operator dispatch bearer token (manual "Run workflow" equivalent).
    dispatch_token: Secret = field(default_factory=lambda: Secret(""))
    # Optional cross-repo PAT for multi-repo estates (same role as in Actions).
    cross_repo_token: Secret = field(default_factory=lambda: Secret(""))

    def agent_credential_env(self) -> dict[str, str]:
        """Env for the Claude CLI. OAuth wins: Claude Code prefers
        ANTHROPIC_API_KEY when both are set, and a Max subscription (Opus)
        lives on CLAUDE_CODE_OAUTH_TOKEN."""
        if self.claude_code_oauth_token.usable():
            return {"CLAUDE_CODE_OAUTH_TOKEN": self.claude_code_oauth_token.reveal()}
        if self.anthropic_api_key.usable():
            return {"ANTHROPIC_API_KEY": self.anthropic_api_key.reveal()}
        return {}

    def __post_init__(self) -> None:
        if not self.github_app_id:
            raise ConfigError("GITHUB_APP_ID is required")
        if not self.github_app_private_key:
            raise ConfigError("GITHUB_APP_PRIVATE_KEY is required")
        if not self.github_webhook_secret:
            raise ConfigError("GITHUB_WEBHOOK_SECRET is required")
        if "/" not in self.factory_repo:
            raise ConfigError(f"FACTORY_REPO must be owner/repo, got {self.factory_repo!r}")
        if self.max_parallel_default < 1:
            raise ConfigError("MAX_PARALLEL must be >= 1")
        if self.role_timeout_seconds < 60:
            raise ConfigError("ROLE_TIMEOUT_SECONDS must be >= 60")

    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            v = getattr(self, f.name)
            parts.append(f"{f.name}={'Secret(****)' if isinstance(v, Secret) else repr(v)}")
        return f"Config({', '.join(parts)})"


def _private_key(e: dict[str, str]) -> str:
    """The App key, plain or base64.

    `docker run --env-file` cannot carry multi-line values, so deployments
    that pass the key through an env file (the lighthouse-style SSH deploy)
    provide GITHUB_APP_PRIVATE_KEY_B64 instead; the plain variable wins when
    both are set.
    """
    plain = e.get("GITHUB_APP_PRIVATE_KEY", "")
    if plain:
        return plain
    b64 = e.get("GITHUB_APP_PRIVATE_KEY_B64", "")
    if not b64:
        return ""
    import base64
    try:
        return base64.b64decode(b64).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConfigError("GITHUB_APP_PRIVATE_KEY_B64 is not valid base64") from exc


def load_config(env: dict[str, str] | None = None) -> Config:
    e = os.environ if env is None else env
    return Config(
        github_app_id=e.get("GITHUB_APP_ID", ""),
        github_app_private_key=Secret(_private_key(dict(e))),
        github_webhook_secret=Secret(e.get("GITHUB_WEBHOOK_SECRET", "")),
        anthropic_api_key=Secret(e.get("ANTHROPIC_API_KEY", "")),
        claude_code_oauth_token=Secret(e.get("CLAUDE_CODE_OAUTH_TOKEN", "")),
        database_url=e.get("DATABASE_URL", "sqlite:///factory-orchestrator.db"),
        factory_repo=e.get("FACTORY_REPO", "genai-jerry/claude-software-factory"),
        factory_ref=e.get("FACTORY_REF", "v1"),
        engine_name=e.get("ENGINE_NAME", "langgraph"),
        github_api_url=e.get("GITHUB_API_URL", "https://api.github.com"),
        max_parallel_default=int(e.get("MAX_PARALLEL", "4")),
        role_timeout_seconds=int(e.get("ROLE_TIMEOUT_SECONDS", str(45 * 60))),
        max_turns=int(e.get("MAX_TURNS", "100")),
        public_base_url=e.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/"),
        dispatch_token=Secret(e.get("DISPATCH_TOKEN", "")),
        cross_repo_token=Secret(e.get("FACTORY_CROSS_REPO_TOKEN", "")),
    )
