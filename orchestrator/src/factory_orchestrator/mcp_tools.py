"""MCP servers an org added in Compass → Tools, given to Claude sessions.

Compass keeps each server in its `mcp_servers` table: a name, a remote URL
(streamable HTTP or SSE), optional request headers sealed with
CONSOLE_MASTER_KEY, the tools it offered when last tested, which of those
tools are allowed, and where the server is used — Shape, Ask, and builds
(every role run). This module reads that table, as `console_secrets` reads
`orchestrator_secrets`, and turns it into the two things the Claude CLI
needs: an `--mcp-config` file and the `mcp__<server>__<tool>` names for
`--allowedTools`.

Only allowed tools are named, and sessions run with `--strict-mcp-config`,
so a tool the person did not switch on is refused like any tool not on the
list — there is no one to approve it in a headless run.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import sqlalchemy as sa

from .console_secrets import SealedSecretError, decrypt_sealed

log = logging.getLogger("factory-orchestrator.mcp-tools")

SURFACES = ("shape", "ask", "build")
CONFIG_NAME = ".factory-mcp.json"


def cli_name(name: str) -> str:
    """The name as Claude Code spells it in `mcp__<server>__<tool>`."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


@dataclass(frozen=True)
class McpServer:
    name: str
    url: str
    transport: str = "http"
    headers: dict[str, str] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    label: str = ""

    def allowed_tools(self) -> list[str]:
        return [f"mcp__{cli_name(self.name)}__{cli_name(t)}" for t in self.tools]


class McpSource(Protocol):
    def servers(self, surface: str) -> list[McpServer]: ...


class NoMcp:
    """No Compass store: sessions get no MCP servers."""

    def servers(self, surface: str) -> list[McpServer]:
        return []


class ConsoleMcpStore:
    """Reads the org's MCP servers from Compass, re-read on a TTL so a server
    added or switched off in Compass reaches the next session without a restart.

    `org` is the Compass org this orchestrator serves (CONSOLE_ORG). Without
    one, servers from a single org are used; servers from several orgs and no
    choice give none, rather than one org's tools in another's runs.
    """

    def __init__(self, database_url: str, master_key_b64: str, org: str | None = None,
                 ttl_seconds: float = 60.0, engine: sa.Engine | None = None):
        self.engine = engine or sa.create_engine(database_url, future=True)
        self.master_key = master_key_b64
        self.org = org or None
        self.ttl = ttl_seconds
        self._rows: list[dict[str, Any]] | None = None
        self._at = 0.0

    def _load(self) -> list[dict[str, Any]]:
        if self._rows is not None and time.monotonic() - self._at < self.ttl:
            return self._rows
        try:
            with self.engine.connect() as cx:
                rows = [dict(r._mapping) for r in cx.execute(sa.text(
                    "SELECT org_id, name, label, transport, url, encrypted_headers, tools, "
                    "use_shape, use_ask, use_build FROM mcp_servers WHERE enabled"))]
        except Exception as e:  # noqa: BLE001 - an older Compass, or a flaky DB: no tools, not a failed run
            log.warning("could not read Compass MCP servers (%s) - sessions get none", e)
            rows = self._rows or []
        orgs = {str(r["org_id"]) for r in rows}
        if self.org is not None:
            rows = [r for r in rows if str(r["org_id"]) == self.org]
        elif len(orgs) > 1:
            log.warning("mcp_servers holds servers for %s orgs - set CONSOLE_ORG; "
                        "sessions get none", len(orgs))
            rows = []
        self._rows, self._at = rows, time.monotonic()
        return rows

    def servers(self, surface: str) -> list[McpServer]:
        if surface not in SURFACES:
            raise ValueError(f"unknown surface {surface!r}")
        out: list[McpServer] = []
        for r in self._load():
            if not r.get(f"use_{surface}"):
                continue
            tools = r.get("tools") or []
            if isinstance(tools, str):
                tools = json.loads(tools)
            allowed = tuple(t["name"] for t in tools
                            if isinstance(t, dict) and t.get("allowed") and t.get("name"))
            if not allowed:
                continue
            headers: dict[str, str] = {}
            if r.get("encrypted_headers"):
                try:
                    headers = json.loads(decrypt_sealed(r["encrypted_headers"], self.master_key))
                except (SealedSecretError, ValueError) as e:
                    log.warning("MCP server %s: headers would not open (%s) - skipped", r["name"], e)
                    continue
            out.append(McpServer(name=r["name"], url=r["url"], transport=r.get("transport") or "http",
                                 headers={str(k): str(v) for k, v in headers.items()},
                                 tools=allowed, label=r.get("label") or r["name"]))
        return out


@dataclass(frozen=True)
class McpWiring:
    """What one session adds to its `claude` command line."""
    argv: list[str]
    allowed: list[str]
    secrets: list[str]
    note: str

    @staticmethod
    def none() -> McpWiring:
        return McpWiring([], [], [], "")


def wire(home: Path, servers: list[McpServer]) -> McpWiring:
    """Write the session's MCP config into its private HOME and say how to use it.

    The file holds header values (API keys), so it is written 0600 into the
    run's own HOME, which is deleted or kept with the run like the rest of it.
    `secrets` are those values, for the caller to redact from transcripts.
    """
    if not servers:
        return McpWiring.none()
    config = {"mcpServers": {
        cli_name(s.name): {"type": "sse" if s.transport == "sse" else "http", "url": s.url,
                           **({"headers": s.headers} if s.headers else {})}
        for s in servers}}
    path = home / CONFIG_NAME
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config, f)
    allowed = [t for s in servers for t in s.allowed_tools()]
    note = "Tools added by your organisation in Compass (MCP): " + "; ".join(
        f"{s.label or s.name} ({', '.join(s.tools)})" for s in servers) + "."
    secrets = [v for s in servers for v in s.headers.values() if len(v) >= 8]
    return McpWiring(["--strict-mcp-config", "--mcp-config", str(path)], allowed, secrets, note)


def store_from_env(env: dict[str, str]) -> McpSource:
    if env.get("CONSOLE_DATABASE_URL") and env.get("CONSOLE_MASTER_KEY"):
        return ConsoleMcpStore(env["CONSOLE_DATABASE_URL"], env["CONSOLE_MASTER_KEY"],
                               org=env.get("CONSOLE_ORG"))
    return NoMcp()
