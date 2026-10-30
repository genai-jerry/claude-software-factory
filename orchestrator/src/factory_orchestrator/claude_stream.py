"""Read headless Claude Code's `--output-format stream-json` output.

Runs ask for the JSON stream so the factory can see what a run used: the
final `result` event carries the session's `usage` and `total_cost_usd` (a
client-side estimate, not the bill), and `system`/`api_retry` events say when
a request is waiting on a rate limit. People still read the run log, so each
event is also turned back into the plain text the log showed before.

Anything this reader does not recognise passes through untouched: a line that
is not JSON (stderr is merged into the same pipe) is printed as it came, and
an unknown event type prints nothing rather than raw JSON. Rate-limit details
are kept wherever an event carries them (`rate_limits`, `rate_limit_info`, or
an event whose type names a rate limit), because the documented fields for a
subscription's allowance exist only in the status line, and the badge should
show them if a headless run ever reports them too.
"""

from __future__ import annotations

import json
from typing import Any

TOKEN_KEYS = ("input_tokens", "output_tokens",
              "cache_read_input_tokens", "cache_creation_input_tokens")
_TOOL_ARG_KEYS = ("command", "file_path", "path", "pattern", "url", "description")


class StreamReader:
    """Feed it stdout lines; read back text for people and numbers for the meter."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.results: list[dict[str, Any]] = []
        self.rate_limit: dict[str, Any] | None = None
        self.retries = 0

    def feed(self, line: str) -> str | None:
        """The readable text for one stdout line, or None when it shows nothing."""
        text = self._render(line)
        if text:
            self.lines.append(text)
        return text

    def text(self) -> str:
        return "".join(self.lines)

    def usage(self) -> dict[str, Any] | None:
        """This process's totals, from its `result` events; None if it sent none."""
        if not self.results:
            return None
        out: dict[str, Any] = {k: 0 for k in TOKEN_KEYS}
        out["cost_usd"] = 0.0
        out["turns"] = 0
        for r in self.results:
            u = r.get("usage") or {}
            for k in TOKEN_KEYS:
                out[k] += int(u.get(k) or 0)
            out["cost_usd"] += float(r.get("total_cost_usd") or 0)
            out["turns"] += int(r.get("num_turns") or 0)
        out["cost_usd"] = round(out["cost_usd"], 6)
        return out

    # -- rendering ---------------------------------------------------------
    def _render(self, line: str) -> str | None:
        stripped = line.strip()
        if not stripped.startswith("{"):
            return line if stripped else None
        try:
            ev = json.loads(stripped)
        except ValueError:
            return line
        if not isinstance(ev, dict):
            return line
        self._note_rate_limit(ev)
        kind, sub = ev.get("type"), ev.get("subtype")
        if kind == "assistant":
            return self._assistant(ev.get("message") or {})
        if kind == "result":
            self.results.append(ev)
            body = ev.get("result")
            return f"{body}\n" if isinstance(body, str) and body else None
        if kind == "system" and sub == "api_retry":
            self.retries += 1
            delay = ev.get("retry_delay_ms")
            wait = f" in {round(delay / 1000)}s" if isinstance(delay, int | float) else ""
            return f"⏳ API retry ({ev.get('error') or ev.get('error_status') or 'error'}){wait}\n"
        return None

    def _assistant(self, message: dict[str, Any]) -> str | None:
        out: list[str] = []
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                out.append(block["text"].rstrip() + "\n")
            elif block.get("type") == "tool_use":
                args = block.get("input") or {}
                hint = next((str(args[k]) for k in _TOOL_ARG_KEYS
                             if isinstance(args, dict) and args.get(k)), "")
                hint = hint.splitlines()[0][:160] if hint else ""
                out.append(f"→ {block.get('name', 'tool')}{' ' + hint if hint else ''}\n")
        return "".join(out) or None

    def _note_rate_limit(self, ev: dict[str, Any]) -> None:
        for key in ("rate_limits", "rate_limit_info"):
            if isinstance(ev.get(key), dict):
                self.rate_limit = ev[key]
                return
        if "rate_limit" in str(ev.get("type") or ""):
            self.rate_limit = {k: v for k, v in ev.items() if k not in ("type", "session_id")}


def run_usage(readers: list[StreamReader]) -> dict[str, Any] | None:
    """One run's usage across its Claude processes (a red-test resume is a second)."""
    totals = [u for u in (r.usage() for r in readers) if u]
    retries = sum(r.retries for r in readers)
    rate_limit = next((r.rate_limit for r in reversed(readers) if r.rate_limit), None)
    if not totals and not retries and rate_limit is None:
        return None
    out: dict[str, Any] = {k: sum(u[k] for u in totals) for k in (*TOKEN_KEYS, "turns")}
    out["cost_usd"] = round(sum(u["cost_usd"] for u in totals), 6)
    out["retries"] = retries
    if rate_limit is not None:
        out["rate_limit"] = rate_limit
    return out
