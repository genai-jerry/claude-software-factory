"""A read-only log tool for Compass → Investigate (MCP over HTTP).

Runs beside a production Docker stack. It reads the containers' own json-file
logs from a read-only mount of /var/lib/docker/containers — no Docker socket,
no shell, no writes — and answers three questions: which services are logging,
what do the logs say about X in a time window, and which errors repeat.

Every line is MASKED here, before it leaves the host: phone numbers, emails,
tokens and secrets, and the values of fields that carry a person's words or
name. There is no switch to turn that off. Masking is best-effort on free text;
it is for keeping a model from being handed customer data by accident, not a
guarantee for logs that print personal data in unstructured sentences.

Environment: LOG_READER_TOKEN (required, bearer), LOG_DIR (default
/var/lib/docker/containers), LOG_SERVICES (optional comma list: only these
compose services or container names), PORT (default 8099).
"""

from __future__ import annotations

import collections
import datetime as dt
import heapq
import json
import os
import re
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROTOCOL = "2025-06-18"
MAX_LIMIT = 500
DEFAULT_LIMIT = 100
MAX_LINE = 1500
MAX_SCAN_BYTES = 300 * 1024 * 1024

# --------------------------------------------------------------------- masking

_PROTECT = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"  # dates and times
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"        # uuids
    r"|\b[0-9a-fA-F]{24,}\b")                                                                # long hex ids
_JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}")
_TOKEN = re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|ghu|xox[baprs]|AKIA)[-_]?[A-Za-z0-9_-]{16,}")
_AUTH = re.compile(r"(?i)\b(bearer|basic)\s+[\w\-.~+/=]{8,}")
_SECRET_KV = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|private[_-]?key|secret|token|password|passwd|pwd|authorization|cookie|set-cookie)"
    r"(\"?\s*[:=]\s*\"?)((?:(?:bearer|basic)\s+)?[^\s\"',;&}]+)")
_PERSON_FIELD = re.compile(
    r"(?i)(\"(?:body|text|content|caption|first_name|last_name|full_name|contact_name|lead_name|display_name|address)\"\s*:\s*)"
    r"\"(?:[^\"\\]|\\.)*\"")
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_PHONE = re.compile(r"(?<![\w])\+?\d[\d \-().]{7,}\d(?![\w])")


def _mask_phone(m: re.Match[str]) -> str:
    raw = m.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 15:
        return raw
    keep = digits[:2] if raw.startswith("+") else ""
    return f"{'+' if raw.startswith('+') else ''}{keep}{'•' * (len(digits) - len(keep) - 4)}{digits[-4:]}"


def mask(text: str) -> str:
    """The line with personal data and secrets masked. Same input, same output."""
    held: list[str] = []

    def hold(m: re.Match[str]) -> str:
        held.append(m.group(0))
        return f"\x00{len(held) - 1}\x00"

    out = _PROTECT.sub(hold, text)
    out = _JWT.sub("[jwt]", out)
    out = _TOKEN.sub("[secret]", out)
    out = _AUTH.sub(lambda m: f"{m.group(1)} [secret]", out)
    out = _SECRET_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[secret]", out)
    out = _PERSON_FIELD.sub(lambda m: f'{m.group(1)}"[redacted]"', out)
    out = _EMAIL.sub(lambda m: f"{m.group(0)[0]}•••@{m.group(1)}", out)
    out = _PHONE.sub(_mask_phone, out)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], out)


# ------------------------------------------------------------------------ logs

def parse_when(value: str | None, now: dt.datetime, default: dt.datetime | None = None) -> dt.datetime | None:
    """`30m`, `2h`, `1d` ago, or an ISO time."""
    if not value:
        return default
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value)
    if m:
        unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        return now - dt.timedelta(seconds=int(m.group(1)) * unit)
    try:
        t = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"cannot read the time {value!r}: use an ISO time like 2026-11-09T17:00:00Z, or 30m / 2h / 1d") from e
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def _docker_time(s: str) -> dt.datetime | None:
    """Docker stamps nanoseconds: 2026-11-09T17:02:55.123456789Z."""
    try:
        return dt.datetime.fromisoformat(re.sub(r"(\.\d{6})\d*Z$", r"\1+00:00", s).replace("Z", "+00:00"))
    except ValueError:
        return None


class Containers:
    """The services on this host, from Docker's container directories."""

    def __init__(self, root: Path, allow: set[str] | None = None):
        self.root = root
        self.allow = allow

    def all(self) -> dict[str, list[Path]]:
        by_service: dict[str, list[Path]] = collections.defaultdict(list)
        if not self.root.is_dir():
            return by_service
        for d in sorted(self.root.iterdir()):
            cfg = d / "config.v2.json"
            if not cfg.is_file():
                continue
            try:
                j = json.loads(cfg.read_text())
            except (OSError, ValueError):
                continue
            name = str(j.get("Name", "")).lstrip("/")
            service = ((j.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service") or name
            if self.allow and service not in self.allow and name not in self.allow:
                continue
            by_service[service].append(d)
        return by_service

    def lines(self, service: str | None, since: dt.datetime, until: dt.datetime) -> Iterator[tuple[dt.datetime, str, str]]:
        """(time, service, message), per container, oldest file first."""
        scanned = 0
        for svc, dirs in sorted(self.all().items()):
            if service and svc != service:
                continue
            for d in dirs:
                files = sorted(d.glob(f"{d.name}-json.log*"), key=lambda p: p.stat().st_mtime)
                for f in files:
                    try:
                        if dt.datetime.fromtimestamp(f.stat().st_mtime, dt.UTC) < since:
                            continue
                        scanned += f.stat().st_size
                        if scanned > MAX_SCAN_BYTES:
                            return
                        with f.open("r", errors="replace") as fh:
                            for raw in fh:
                                try:
                                    rec = json.loads(raw)
                                except ValueError:
                                    continue
                                t = _docker_time(str(rec.get("time", "")))
                                if t is None or t < since or t > until:
                                    continue
                                yield t, svc, str(rec.get("log", "")).rstrip("\n")
                    except OSError:
                        continue


_LEVELS = {
    "error": re.compile(r"\b(ERROR|CRITICAL|FATAL|Traceback|Exception|panic)\b|\"level\"\s*:\s*\"(error|critical|fatal)\"", re.I),
    "warn": re.compile(r"\bWARN(ING)?\b|\"level\"\s*:\s*\"warn", re.I),
}


def _fmt(t: dt.datetime, svc: str, msg: str) -> str:
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z [{svc}] {mask(msg)[:MAX_LINE]}"


class Tools:
    def __init__(self, containers: Containers, now=lambda: dt.datetime.now(dt.UTC)):
        self.c = containers
        self.now = now

    def list_services(self, **_: Any) -> str:
        rows = []
        for svc, dirs in sorted(self.c.all().items()):
            newest = max((f.stat().st_mtime for d in dirs for f in d.glob(f"{d.name}-json.log*")), default=None)
            rows.append(f"- {svc}" + (f" (last wrote {dt.datetime.fromtimestamp(newest, dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')})" if newest else ""))
        return "\n".join(rows) or "No services are logging on this host."

    def search_logs(self, service: str | None = None, query: str | None = None, since: str | None = None,
                    until: str | None = None, level: str | None = None, limit: int | None = None,
                    regex: bool = False, **_: Any) -> str:
        now = self.now()
        start = parse_when(since, now, now - dt.timedelta(hours=1))
        end = parse_when(until, now, now)
        n = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        if level and level not in _LEVELS:
            raise ValueError("level must be error or warn")
        pat = re.compile(query if regex else re.escape(query), re.I) if query else None
        # The newest n by time, across every service (not by scan order).
        kept: list[tuple[dt.datetime, int, str, str]] = []
        total = 0
        for t, svc, msg in self.c.lines(service, start, end):
            if level and not _LEVELS[level].search(msg):
                continue
            # Match what the reader will see: the masked line, never the raw one.
            if pat and not pat.search(mask(msg)):
                continue
            total += 1
            heapq.heappush(kept, (t, total, svc, msg))
            if len(kept) > n:
                heapq.heappop(kept)
        head = f"{total} matching line{'s' if total != 1 else ''} from {start.strftime('%Y-%m-%dT%H:%M:%SZ')} to {end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        if total > n:
            head += f"; showing the newest {n}. Narrow the time window or add a filter to see the rest"
        body = "\n".join(_fmt(t, svc, msg) for t, _, svc, msg in sorted(kept))
        return f"{head}.\n\n{body}" if body else f"{head}."

    def error_summary(self, service: str | None = None, since: str | None = None, until: str | None = None, **_: Any) -> str:
        now = self.now()
        start = parse_when(since, now, now - dt.timedelta(hours=24))
        end = parse_when(until, now, now)
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for t, svc, msg in self.c.lines(service, start, end):
            if not _LEVELS["error"].search(msg):
                continue
            shape = re.sub(r"\d+", "#", mask(msg))[:160]
            g = groups.setdefault((svc, shape), {"n": 0, "first": t, "last": t})
            g["n"] += 1
            g["last"] = max(g["last"], t)
            g["first"] = min(g["first"], t)
        if not groups:
            return f"No errors from {start.strftime('%Y-%m-%dT%H:%M:%SZ')} to {end.strftime('%Y-%m-%dT%H:%M:%SZ')}."
        top = sorted(groups.items(), key=lambda kv: -kv[1]["n"])[:15]
        lines = [f"{g['n']}× [{svc}] {shape}  (first {g['first'].strftime('%H:%M:%SZ')}, last {g['last'].strftime('%Y-%m-%d %H:%M:%SZ')})" for (svc, shape), g in top]
        return "Repeated errors, most frequent first (digits shown as #):\n" + "\n".join(lines)


TOOL_DEFS = [
    {"name": "list_services", "description": "The services logging on the production host, and when each last wrote.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "search_logs",
     "description": "Search production logs. Lines are masked: phone numbers, emails, secrets and message text never appear. Default window is the last hour; times are ISO or 30m / 2h / 1d ago.",
     "inputSchema": {"type": "object", "properties": {
         "service": {"type": "string", "description": "A service from list_services; omit for all"},
         "query": {"type": "string", "description": "Case-insensitive text to find"},
         "regex": {"type": "boolean", "description": "Treat query as a regular expression"},
         "since": {"type": "string"}, "until": {"type": "string"},
         "level": {"type": "string", "enum": ["error", "warn"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}}, "additionalProperties": False}},
    {"name": "error_summary",
     "description": "The errors that repeat most in a window (default 24h), grouped by message shape, with counts and first/last times. A good first look.",
     "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}, "since": {"type": "string"}, "until": {"type": "string"}}, "additionalProperties": False}},
]
for t in TOOL_DEFS:
    t["annotations"] = {"title": t["name"].replace("_", " ").title(), "readOnlyHint": True}


# -------------------------------------------------------------------- protocol

def handle(rpc: dict[str, Any], tools: Tools) -> dict[str, Any] | None:
    method, rid = rpc.get("method"), rpc.get("id")
    if rid is None:
        return None  # a notification
    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    def err(code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "log-reader", "version": "1"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOL_DEFS})
    if method == "tools/call":
        params = rpc.get("params") or {}
        fn = getattr(tools, str(params.get("name")), None)
        if params.get("name") not in {t["name"] for t in TOOL_DEFS} or fn is None:
            return err(-32602, f"unknown tool {params.get('name')!r}")
        try:
            return ok({"content": [{"type": "text", "text": fn(**(params.get("arguments") or {}))}]})
        except (ValueError, TypeError) as e:
            return ok({"isError": True, "content": [{"type": "text", "text": str(e)}]})
    return err(-32601, f"method not found: {method}")


def make_handler(tools: Tools, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # request lines carry nothing worth keeping
            return

        def _send(self, status: int, body: bytes = b"", ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            got = self.headers.get("authorization", "")
            key = self.headers.get("x-api-key", "")
            return bool(token) and (got == f"Bearer {token}" or key == token)

        def do_GET(self) -> None:
            if self.path == "/healthz":
                return self._send(200, b'{"ok":true}')
            self._send(405, b'{"error":"POST /mcp"}')

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/mcp":
                return self._send(404, b'{"error":"POST /mcp"}')
            if not self._authorised():
                return self._send(401, b'{"error":"token required"}')
            try:
                rpc = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            except ValueError:
                return self._send(400, b'{"error":"not JSON"}')
            replies = [handle(r, tools) for r in (rpc if isinstance(rpc, list) else [rpc])]
            replies = [r for r in replies if r is not None]
            if not replies:
                return self._send(202)
            self._send(200, json.dumps(replies if isinstance(rpc, list) else replies[0]).encode())

    return Handler


def main() -> None:
    token = os.environ.get("LOG_READER_TOKEN", "")
    if len(token) < 24:
        sys.exit("LOG_READER_TOKEN must be set, at least 24 characters (openssl rand -hex 24)")
    allow = {s.strip() for s in os.environ.get("LOG_SERVICES", "").split(",") if s.strip()} or None
    tools = Tools(Containers(Path(os.environ.get("LOG_DIR", "/var/lib/docker/containers")), allow))
    port = int(os.environ.get("PORT", "8099"))
    print(f"log-reader on :{port}, services: {', '.join(sorted(allow)) if allow else 'all'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(tools, token)).serve_forever()


if __name__ == "__main__":
    main()
