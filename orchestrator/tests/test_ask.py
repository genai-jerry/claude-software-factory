"""A person's question about a thread, answered by a read-only Claude session."""

from __future__ import annotations

import os
from types import SimpleNamespace

import httpx
import pytest

from factory_orchestrator.ask import ASK_TOOLS, AskError, answer_question
from factory_orchestrator.config import load_config
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.repo_cache import RepoCache
from factory_orchestrator.role_runner import FactorySource, RoleRunner
from factory_orchestrator.webhook import create_app

from .fake_repo import FakeRepo
from .test_config import BASE
from .test_role_runner import (
    make_bare_origin,
    make_consuming_repo,
    make_fake_claude,
    make_local_factory,
)

RESULT = ('{"type":"result","result":"It stopped after two rework rounds. Reply on #11 to allow one more.",'
          '"is_error":false,"num_turns":3,"total_cost_usd":0.03,'
          '"usage":{"input_tokens":120,"output_tokens":40}}')


def engine_for(tmp_path, on_run=RESULT, env=None):
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60", **(env or {})})
    source = FactorySource(cfg, local_path=str(make_local_factory(tmp_path)))
    origin = make_bare_origin(make_consuming_repo(tmp_path), tmp_path / "r.git")
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin),
                      env={"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    (tmp_path / "ws").mkdir()
    out = tmp_path / "captured"
    claude = make_fake_claude(tmp_path, out, on_run=f"echo '{on_run}'\n" if on_run else None)
    runner = RoleRunner(cfg, source, workspace_root=str(tmp_path / "ws"),
                        claude_bin=str(claude), repo_cache=cache)
    engine = SimpleNamespace(
        cfg=cfg, runner=runner, probe=lambda m: True,
        port=lambda o, r: FakeRepo(owner=o, repo=r),
        app=SimpleNamespace(installation_token=lambda *a, **k: "ghs_secret"))
    return engine, out


def test_a_question_is_answered_in_a_read_only_session(tmp_path):
    engine, out = engine_for(tmp_path)
    got = answer_question(engine, owner="o", repo="r", question="Why is #11 blocked?",
                          context="[agent] Reviewer: round 2 blocked.")
    assert got["answer"].startswith("It stopped after two rework rounds.")
    assert got["usage"] == {"input_tokens": 120, "output_tokens": 40, "cost_usd": 0.03}
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--allowedTools") + 1] == ASK_TOOLS
    assert "--output-format" in argv and "Write" not in ASK_TOOLS and "Edit" not in ASK_TOOLS
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Why is #11 blocked?" in prompt and "round 2 blocked" in prompt
    # no GitHub token reaches the session, and its checkout is gone afterwards
    assert "GH_TOKEN=\n" in next(out.glob("env-*.txt")).read_text() + "\n"
    assert not list((tmp_path / "ws").iterdir())


def test_the_default_answer_follows_the_writing_standard(tmp_path):
    engine, out = engine_for(tmp_path)
    answer_question(engine, owner="o", repo="r", question="why?", context="thread")
    prompt = next(out.glob("prompt-*.txt")).read_text()
    for rule in ("15 words or fewer", "You need to:", "at most 5 bullets", "120 words", "active voice"):
        assert rule in prompt, rule


def test_the_callers_instructions_replace_the_default_style(tmp_path):
    engine, out = engine_for(tmp_path)
    answer_question(engine, owner="o", repo="r", question="why?", context="[1] a source",
                    instructions="Cite sources as [n].")
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Cite sources as [n]." in prompt and "at most 150 words" not in prompt
    assert "[1] a source" in prompt


def test_an_empty_question_or_missing_credential_is_refused(tmp_path):
    engine, _ = engine_for(tmp_path)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="  ", context="")
    assert e.value.status == 400
    engine.cfg = SimpleNamespace(agent_credential_env=lambda: {})
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="why?", context="")
    assert e.value.status == 503 and "credential" in str(e.value)


def test_a_usage_limit_is_named(tmp_path):
    engine, _ = engine_for(tmp_path, on_run="You've hit your session limit · resets 2:50pm (UTC)")
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="why?", context="")
    assert e.value.status == 429 and "usage limit" in str(e.value)


async def test_the_endpoint_needs_the_operator_token_and_returns_the_answer(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "Because of the cap.", "model": "m", "usage": {}}
    app.state.asker = asker
    body = {"owner": "o", "repo": "r", "question": "why?", "context": "thread", "branch": "factory/epic-34",
            "instructions": "Cite sources as [n]."}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/ask", json=body)).status_code == 401
        ok = await c.post("/ask", json=body, headers={"authorization": "Bearer op-token"})
        assert ok.status_code == 200 and ok.json()["answer"] == "Because of the cap."
        bad = await c.post("/ask", json={"owner": "o"}, headers={"authorization": "Bearer op-token"})
        assert bad.status_code == 400
    assert seen["branch"] == "factory/epic-34" and seen["question"] == "why?"
    assert seen["instructions"] == "Cite sources as [n]."
