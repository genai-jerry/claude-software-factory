"""The read-only log tool for Compass → Investigate: masking, searching, the protocol."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("log_reader", Path(__file__).resolve().parents[2] / "tools/log-reader/log_reader.py")
lr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lr)

NOW = dt.datetime(2026, 11, 9, 18, 0, 0, tzinfo=dt.UTC)


def container(root: Path, cid: str, service: str, name: str, lines: list[tuple[str, str]]) -> None:
    d = root / cid
    d.mkdir()
    (d / "config.v2.json").write_text(json.dumps({"Name": f"/{name}", "Config": {"Labels": {"com.docker.compose.service": service}}}))
    (d / f"{cid}-json.log").write_text("".join(json.dumps({"log": msg + "\n", "stream": "stdout", "time": t}) + "\n" for t, msg in lines))


@pytest.fixture
def tools(tmp_path):
    container(tmp_path, "aaa", "beacon-api", "beacon-api-1", [
        ("2026-11-09T10:00:00.000000000Z", "ERROR long ago"),
        ("2026-11-09T17:02:55.123456789Z", "INFO inbound from +919876543210 ok"),
        ("2026-11-09T17:30:00.000000000Z", "ERROR flow 42 not found for run 9001"),
        ("2026-11-09T17:31:00.000000000Z", "ERROR flow 43 not found for run 9002"),
    ])
    container(tmp_path, "bbb", "beacon-worker", "beacon-worker-1", [("2026-11-09T17:45:00.000000000Z", "WARNING retry 3 for lead jerry@example.com")])
    return lr.Tools(lr.Containers(tmp_path), now=lambda: NOW)


def test_masking_keeps_the_shape_and_hides_the_person():
    assert lr.mask("from +919876543210 to 9876543210") == "from +91••••••3210 to ••••••3210"
    assert lr.mask("lead jerry@example.com wrote") == "lead j•••@example.com wrote"
    assert lr.mask("Authorization: Bearer abcdef1234567890xyz") == "Authorization: [secret]"
    assert lr.mask("api_key=sk-live-abcdef1234567890abcd retry") == "api_key=[secret] retry"
    assert lr.mask("token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdEFGH") == "token: [secret]"
    assert lr.mask('{"body": "hi, my name is Asha", "status": "sent"}') == '{"body": "[redacted]", "status": "sent"}'
    # What must survive: times, ids, ordinary numbers.
    safe = "2026-11-09T17:02:55.123Z run 9001 id 3f2504e0-4f89-11d3-9a0c-0305e82c3301 took 1234 ms"
    assert lr.mask(safe) == safe
    assert lr.mask("+919876543210") == lr.mask("+919876543210")  # the same value masks the same way


def test_search_masks_and_filters_by_window_and_text(tools):
    out = tools.search_logs(service="beacon-api", since="2h")
    assert "inbound from +91••••••3210 ok" in out and "9876543210" not in out
    assert "long ago" not in out  # outside the window
    errs = tools.search_logs(query="not found", level="error")
    assert errs.count("flow 4") == 2 and "2 matching lines" in errs


def test_search_cannot_be_used_to_probe_masked_values(tools):
    # Matching runs on the masked line, so a guessed phone number finds nothing.
    assert "0 matching lines" in tools.search_logs(query="9876543210")
    assert "1 matching line" in tools.search_logs(query="•••3210")


def test_a_limit_keeps_the_newest_and_says_so(tools):
    out = tools.search_logs(since="1d", limit=2)
    assert "showing the newest 2" in out
    assert "long ago" not in out and "retry 3" in out


def test_error_summary_groups_by_shape(tools):
    out = tools.error_summary(since="1d")
    assert "2× [beacon-api] ERROR flow # not found for run #" in out
    assert "long ago" in out
    assert "jerry@example.com" not in out


def test_services_and_allowlist(tmp_path, tools):
    assert "- beacon-api" in tools.list_services() and "- beacon-worker" in tools.list_services()
    only = lr.Tools(lr.Containers(tmp_path, {"beacon-worker"}), now=lambda: NOW)
    assert "beacon-api" not in only.list_services()
    assert "No matching" not in only.search_logs(since="1d")


def test_bad_times_and_levels_are_reported_not_raised(tools):
    assert lr.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_logs", "arguments": {"since": "yesterday-ish"}}}, tools)["result"]["isError"]
    assert lr.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_logs", "arguments": {"level": "debug"}}}, tools)["result"]["isError"]
    assert lr.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}}, tools)["error"]["code"] == -32602


def serve(tools, token="t" * 32):
    server = ThreadingHTTPServer(("127.0.0.1", 0), lr.make_handler(tools, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/mcp"


def post(url, body, token=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **({"authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, (json.loads(r.read() or b"null") if r.status == 200 else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def test_the_protocol_over_http_needs_the_token_and_lists_read_only_tools(tools):
    server, url = serve(tools)
    try:
        assert post(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0] == 401
        assert post(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "wrong")[0] == 401
        status, got = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, "t" * 32)
        assert status == 200 and got["result"]["serverInfo"]["name"] == "log-reader"
        assert post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, "t" * 32)[0] == 202
        _, listed = post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "t" * 32)
        assert [t["name"] for t in listed["result"]["tools"]] == ["list_services", "search_logs", "error_summary"]
        assert all(t["annotations"]["readOnlyHint"] for t in listed["result"]["tools"])
        _, called = post(url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_logs", "arguments": {"query": "not found", "since": "1d"}}}, "t" * 32)
        assert "flow 42 not found" in called["result"]["content"][0]["text"]
    finally:
        server.shutdown()
