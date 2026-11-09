"""MCP servers an org added in Compass → Tools, given to Claude sessions.

Three ways in, whichever the deployment has:
- `/ask` carries the org's servers in its body (`from_payload`): Shape and Ask.
- `ConsoleMcpPull` asks the Compass that dispatched a repo, over the same
  dispatch-token channel as attachments and token re-minting: role runs on a
  deployment without CONSOLE_DATABASE_URL (production).
- `ConsoleMcpStore` reads Compass's table directly, where the database is shared.

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

import httpx
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
    def servers(self, surface: str, repo: str | None = None) -> list[McpServer]: ...


class NoMcp:
    """No Compass store: sessions get no MCP servers."""

    def servers(self, surface: str, repo: str | None = None) -> list[McpServer]:
        return []


def from_payload(items: Any, surface: str) -> list[McpServer]:
    """Servers as Compass sends them (in /ask, or from its endpoint), for one surface.

    Each item: name, label, transport, url, headers {}, tools [allowed names],
    use_shape / use_ask / use_build. Anything malformed is skipped, never fatal.
    """
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}")
    out: list[McpServer] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not it.get(f"use_{surface}"):
            continue
        name, url = it.get("name"), it.get("url")
        tools = tuple(t for t in (it.get("tools") or []) if isinstance(t, str) and t)
        if not isinstance(name, str) or not name or not isinstance(url, str) or not url.startswith(("https://", "http://")) or not tools:
            continue
        headers = it.get("headers") if isinstance(it.get("headers"), dict) else {}
        out.append(McpServer(name=name, url=url, transport="sse" if it.get("transport") == "sse" else "http",
                             headers={str(k): str(v) for k, v in headers.items()},
                             tools=tools, label=str(it.get("label") or name)))
    return out


PULL_PATH = "/api/orchestrator/mcp-servers"


class ConsoleMcpPull:
    """Ask the Compass that dispatched a repo for its org's servers.

    `origin_of(owner, repo)` is the Compass origin a dispatch registered (the
    same one images and tokens come from). Cached per repo for a minute; a
    Compass that is unknown, down or too old gives no tools, never a failed run.
    """

    def __init__(self, dispatch_token: str, origin_of, *, client: httpx.Client | None = None,
                 ttl_seconds: float = 60.0, timeout: float = 10.0):
        self.dispatch_token = dispatch_token
        self.origin_of = origin_of
        self.ttl = ttl_seconds
        self.timeout = timeout
        self._client = client
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _items(self, repo: str) -> list[dict[str, Any]]:
        hit = self._cache.get(repo)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        owner, _, name = repo.partition("/")
        origin = self.origin_of(owner, name) if self.origin_of else None
        items: list[dict[str, Any]] = []
        if origin and self.dispatch_token:
            client = self._client or httpx.Client(timeout=self.timeout)
            try:
                r = client.get(f"{origin.rstrip('/')}{PULL_PATH}", params={"repo": repo},
                               headers={"Authorization": f"Bearer {self.dispatch_token}"})
                if r.status_code < 400:
                    items = list((r.json() or {}).get("servers") or [])
                else:
                    log.warning("mcp: Compass %s returned %s for %s", PULL_PATH, r.status_code, repo)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("mcp: could not read tools from the Compass for %s: %s", repo, e)
                items = hit[1] if hit else []
            finally:
                if self._client is None:
                    client.close()
        self._cache[repo] = (time.monotonic(), items)
        return items

    def servers(self, surface: str, repo: str | None = None) -> list[McpServer]:
        return from_payload(self._items(repo), surface) if repo else []


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

    def servers(self, surface: str, repo: str | None = None) -> list[McpServer]:
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


def store_from_env(env: dict[str, str], *, dispatch_token: str = "", origin_of=None) -> McpSource:
    """The Compass database where it is shared; else ask the dispatching Compass."""
    if env.get("CONSOLE_DATABASE_URL") and env.get("CONSOLE_MASTER_KEY"):
        return ConsoleMcpStore(env["CONSOLE_DATABASE_URL"], env["CONSOLE_MASTER_KEY"],
                               org=env.get("CONSOLE_ORG"))
    if dispatch_token and origin_of:
        return ConsoleMcpPull(dispatch_token, origin_of)
    return NoMcp()
