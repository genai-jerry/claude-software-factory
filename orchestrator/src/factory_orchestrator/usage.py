"""What the factory's Claude runs have used, for the Console's usage badge.

`GET /usage` answers from the run ledger alone. Each finished run stores the
tokens and estimated cost Claude reported (`guards.usage`, from the JSON
stream), and a run stopped by a usage limit stores the limit's message and
reset time (reconcile.usage_limit_error). A subscription's remaining
allowance has no documented headless source, so the badge shows:

- the last five hours' runs, tokens and estimated cost (the subscription's
  session window is five hours);
- whether a limit is in force now, when it resets, and how many issues are
  waiting for that reset;
- a percentage only if a run ever reported one (`rate_limit` in its usage).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .claude_stream import TOKEN_KEYS
from .ledger import Ledger
from .reconcile import as_utc, limit_resets_at, run_kind

WINDOW = dt.timedelta(hours=5)


def _usage_of(run: dict[str, Any]) -> dict[str, Any]:
    try:
        guards = json.loads(run.get("guards") or "{}")
    except ValueError:
        return {}
    u = guards.get("usage") if isinstance(guards, dict) else None
    return u if isinstance(u, dict) else {}


def summarize(ledger: Ledger, now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    recent = ledger.list_runs(since=now - WINDOW, limit=2000)
    tokens = dict.fromkeys(TOKEN_KEYS, 0)
    cost = 0.0
    measured = 0
    rate_limit: dict[str, Any] | None = None
    for run in recent:  # newest first
        u = _usage_of(run)
        if not u:
            continue
        measured += 1
        for k in TOKEN_KEYS:
            tokens[k] += int(u.get(k) or 0)
        cost += float(u.get("cost_usd") or 0)
        if rate_limit is None and isinstance(u.get("rate_limit"), dict):
            rate_limit = u["rate_limit"]

    # A limit is in force while the newest limit failure has not reset yet.
    # Issues waiting on it: those whose latest run is that kind of failure.
    resets_at: dt.datetime | None = None
    message = None
    waiting: set[tuple[str, int]] = set()
    latest_per_issue: dict[tuple[str, int], dict[str, Any]] = {}
    for run in recent:
        latest_per_issue.setdefault((run["repo"], run["issue"]), run)
    for key, run in latest_per_issue.items():
        if run_kind(run) != "limit":
            continue
        finished = as_utc(run.get("finished_at")) or now
        at = limit_resets_at(run.get("error") or "", finished)
        if at <= now:
            continue
        waiting.add(key)
        if resets_at is None or at > resets_at:
            resets_at, message = at, run.get("error")

    return {
        "as_of": now.isoformat(),
        "window_hours": WINDOW.total_seconds() / 3600,
        "runs": len(recent),
        "measured_runs": measured,
        "active_runs": sum(1 for r in recent if r.get("finished_at") is None),
        "tokens": tokens,
        "total_tokens": sum(tokens.values()),
        "cost_usd": round(cost, 4),
        "limit": {
            "reached": resets_at is not None,
            "resets_at": resets_at.isoformat() if resets_at else None,
            "waiting_issues": sorted(f"{r}#{n}" for r, n in waiting),
            "message": message,
        },
        "rate_limit": rate_limit,
    }
