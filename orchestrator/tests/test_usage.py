"""Usage capture from Claude's JSON stream, and the GET /usage summary."""

from __future__ import annotations

import datetime as dt
import json

from factory_orchestrator.claude_stream import StreamReader, run_usage
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.reconcile import usage_limit_error
from factory_orchestrator.usage import summarize


def _line(ev):
    return json.dumps(ev) + "\n"


def test_the_stream_reads_back_as_text_and_usage():
    r = StreamReader()
    shown = [r.feed(x) for x in (
        _line({"type": "system", "subtype": "init", "session_id": "s"}),
        _line({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Reading the spec."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q\nmore"}}]}}),
        _line({"type": "user", "message": {"content": [{"type": "tool_result"}]}}),
        _line({"type": "system", "subtype": "api_retry", "error": "rate_limit",
               "retry_delay_ms": 30000}),
        "plain stderr line\n",
        _line({"type": "result", "subtype": "success", "result": "Done.", "num_turns": 7,
               "total_cost_usd": 0.42,
               "usage": {"input_tokens": 1000, "output_tokens": 200,
                         "cache_read_input_tokens": 5000}}),
    )]
    assert shown == [None, "Reading the spec.\n→ Bash pytest -q\n", None,
                     "⏳ API retry (rate_limit) in 30s\n", "plain stderr line\n", "Done.\n"]
    assert "→ Bash pytest -q" in r.text()
    second = StreamReader()  # a red-test resume is a second process
    second.feed(_line({"type": "result", "result": "Fixed.", "num_turns": 2,
                       "total_cost_usd": 0.08, "usage": {"input_tokens": 10, "output_tokens": 5}}))
    u = run_usage([r, second])
    assert u["input_tokens"] == 1010 and u["output_tokens"] == 205
    assert u["cache_read_input_tokens"] == 5000 and u["turns"] == 9
    assert u["cost_usd"] == 0.5 and u["retries"] == 1 and "rate_limit" not in u


def test_a_reported_rate_limit_is_kept():
    r = StreamReader()
    r.feed(_line({"type": "rate_limit_event", "rate_limit_info": {
        "five_hour": {"used_percentage": 62, "resets_at": 1793372400}}}))
    assert run_usage([r])["rate_limit"]["five_hour"]["used_percentage"] == 62
    assert run_usage([StreamReader()]) is None


def test_summary_totals_the_window_and_names_a_limit_in_force(tmp_path):
    ledger = Ledger(f"sqlite:///{tmp_path}/u.db")
    now = dt.datetime.now(dt.UTC)
    ok = ledger.start_run(repo="o/a", issue=1, role="qa", trigger="t")
    ledger.finish_run(ok, outcome="success", guards={"usage": {
        "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.25}})
    reset = (now + dt.timedelta(hours=2)).strftime("%-I:%M%p").lower()
    hit = ledger.start_run(repo="o/b", issue=2, role="release", trigger="t")
    ledger.finish_run(hit, outcome="error", error=usage_limit_error(
        f"You've hit your session limit · resets {reset} (UTC)"))
    ledger.start_run(repo="o/a", issue=3, role="implementer", trigger="t")  # live
    s = summarize(ledger, now + dt.timedelta(seconds=1))
    assert s["runs"] == 3 and s["measured_runs"] == 1 and s["active_runs"] == 1
    assert s["total_tokens"] == 150 and s["cost_usd"] == 0.25
    assert s["limit"]["reached"] is True and s["limit"]["waiting_issues"] == ["o/b#2"]
    assert s["limit"]["resets_at"].startswith(
        (now + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))
    later = summarize(ledger, now + dt.timedelta(hours=3))
    assert later["limit"]["reached"] is False
