"""MCP servers from Compass → Tools reach Claude sessions, and only what was allowed."""

from __future__ import annotations

import base64
import json
import os
import stat

import sqlalchemy as sa

from factory_orchestrator.ask import answer_question
from factory_orchestrator.console_secrets import seal
from factory_orchestrator.mcp_tools import ConsoleMcpStore, McpServer, NoMcp, wire

from .test_ask import engine_for
from .test_role_runner import build_runner

KEY = base64.b64encode(b"k" * 32).decode()
ORG = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def tools(*allowed: str, off: tuple[str, ...] = ()) -> str:
    return json.dumps([{"name": t, "allowed": True} for t in allowed]
                      + [{"name": t, "allowed": False} for t in off])


def store_with(tmp_path, rows, org=ORG, table=True) -> ConsoleMcpStore:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'compass.db'}", future=True)
    if table:
        with engine.begin() as cx:
            cx.execute(sa.text(
                "CREATE TABLE mcp_servers (org_id TEXT, name TEXT, label TEXT, transport TEXT, url TEXT, "
                "encrypted_headers TEXT, tools TEXT, use_shape INT, use_ask INT, use_build INT, enabled INT)"))
            for r in rows:
                cx.execute(sa.text(
                    "INSERT INTO mcp_servers VALUES (:org_id, :name, :label, :transport, :url, "
                    ":encrypted_headers, :tools, :use_shape, :use_ask, :use_build, :enabled)"),
                    {"org_id": ORG, "label": None, "transport": "http", "encrypted_headers": None,
                     "use_shape": 1, "use_ask": 1, "use_build": 1, "enabled": 1, **r})
    return ConsoleMcpStore("unused", KEY, org=org, engine=engine)


def test_only_allowed_tools_of_enabled_servers_for_the_surface(tmp_path):
    store = store_with(tmp_path, [
        {"name": "sarvam", "url": "https://docs.sarvam.ai/_mcp/server", "tools": tools("searchDocs", off=("deleteAll",))},
        {"name": "shape_only", "url": "https://a.example/mcp", "tools": tools("look"), "use_build": 0},
        {"name": "off", "url": "https://b.example/mcp", "tools": tools("x"), "enabled": 0},
        {"name": "nothing_allowed", "url": "https://c.example/mcp", "tools": tools(off=("y",))},
        {"name": "theirs", "url": "https://d.example/mcp", "tools": tools("z"), "org_id": OTHER},
    ])
    build = store.servers("build")
    assert [s.name for s in build] == ["sarvam"]
    assert build[0].tools == ("searchDocs",)
    assert [s.name for s in store.servers("shape")] == ["sarvam", "shape_only"]


def test_headers_are_opened_with_the_master_key(tmp_path):
    sealed = seal(json.dumps({"Authorization": "Bearer sk-live-123456"}), KEY)
    store = store_with(tmp_path, [{"name": "api", "url": "https://x/mcp", "tools": tools("t"), "encrypted_headers": sealed},
                                  {"name": "bad", "url": "https://y/mcp", "tools": tools("t"), "encrypted_headers": "v1.x.y.z"}])
    got = store.servers("ask")
    assert [s.name for s in got] == ["api"]
    assert got[0].headers == {"Authorization": "Bearer sk-live-123456"}


def test_servers_of_several_orgs_without_a_choice_give_none(tmp_path):
    store = store_with(tmp_path, [{"name": "a", "url": "u", "tools": tools("t")},
                                  {"name": "b", "url": "u", "tools": tools("t"), "org_id": OTHER}], org=None)
    assert store.servers("build") == []


def test_an_older_compass_without_the_table_gives_none(tmp_path):
    assert store_with(tmp_path, [], table=False).servers("build") == []


def test_wire_writes_a_private_config_and_names_the_tools(tmp_path):
    w = wire(tmp_path, [McpServer(name="sarvam docs", url="https://docs.sarvam.ai/_mcp/server", tools=("search.docs",),
                                  headers={"x-api-key": "secret-value-1"}, label="Sarvam"),
                        McpServer(name="legacy", url="https://l/sse", transport="sse", tools=("t",))])
    path = tmp_path / ".factory-mcp.json"
    assert w.argv == ["--strict-mcp-config", "--mcp-config", str(path)]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    cfg = json.loads(path.read_text())["mcpServers"]
    assert cfg["sarvam_docs"] == {"type": "http", "url": "https://docs.sarvam.ai/_mcp/server",
                                  "headers": {"x-api-key": "secret-value-1"}}
    assert cfg["legacy"] == {"type": "sse", "url": "https://l/sse"}
    assert w.allowed == ["mcp__sarvam_docs__search_docs", "mcp__legacy__t"]
    assert w.secrets == ["secret-value-1"]
    assert "Sarvam (search.docs)" in w.note
    assert wire(tmp_path, []).argv == [] and NoMcp().servers("build") == []


class Fixed:
    def __init__(self, by_surface):
        self.by_surface = by_surface

    def servers(self, surface):
        return self.by_surface.get(surface, [])


SARVAM = McpServer(name="sarvam", url="https://docs.sarvam.ai/_mcp/server", tools=("searchDocs",), label="Sarvam")


def test_a_shape_session_gets_the_shape_servers_and_is_told_about_them(tmp_path):
    engine, out = engine_for(tmp_path)
    engine.runner.mcp = Fixed({"shape": [SARVAM]})
    answer_question(engine, owner="o", repo="r", question="what STT model?", context="", mode="shape")
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert "mcp__sarvam__searchDocs" in argv[argv.index("--allowedTools") + 1]
    assert "--strict-mcp-config" in argv and "--mcp-config" in argv
    assert "Sarvam (searchDocs)" in next(out.glob("prompt-*.txt")).read_text()


def test_an_ask_session_does_not_get_shape_only_servers(tmp_path):
    engine, out = engine_for(tmp_path)
    engine.runner.mcp = Fixed({"shape": [SARVAM]})
    answer_question(engine, owner="o", repo="r", question="why?", context="")
    argv = next(out.glob("argv-*.txt")).read_text()
    assert "--mcp-config" not in argv and "mcp__" not in argv


def test_a_build_run_gets_the_build_servers_and_redacts_their_headers(tmp_path):
    cfg, runner, out = build_runner(tmp_path)
    runner.mcp = Fixed({"build": [McpServer(name="sarvam", url="https://s/mcp", tools=("searchDocs",),
                                            headers={"api-subscription-key": "sk_sarvam_abcdef"})]})
    outcome = runner.run(owner="o", repo="r", role="intake", issue=5,
                         model="claude-sonnet-5", github_token="ghs_secret_token")
    assert outcome.status == "success"
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--allowedTools") + 1].endswith(",mcp__sarvam__searchDocs")
    assert argv[argv.index("--mcp-config") + 1].endswith(".factory-mcp.json")
    assert runner._redact("key sk_sarvam_abcdef here") == "key *** here"  # noqa: SLF001


def test_a_build_run_without_servers_is_unchanged(tmp_path):
    cfg, runner, out = build_runner(tmp_path)
    runner.run(owner="o", repo="r", role="intake", issue=5, model="claude-sonnet-5", github_token="ghs_secret_token")
    argv = next(out.glob("argv-*.txt")).read_text()
    assert "--mcp-config" not in argv and "mcp__" not in argv
