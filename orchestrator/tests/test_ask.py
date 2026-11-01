"""A person's question about a thread, answered by a read-only Claude session."""

from __future__ import annotations

import os
from types import SimpleNamespace

import httpx
import pytest

import base64

from factory_orchestrator.ask import ASK_TOOLS, MODES, AskError, answer_question, check_images
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


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()


def test_images_land_beside_the_checkout_and_are_named_in_the_prompt(tmp_path):
    # The fake claude lists what it finds where the prompt says to look.
    listing = tmp_path / "attachments.txt"
    engine, out = engine_for(tmp_path)
    (tmp_path / "claude-hook.sh").write_text(f"ls \"$HOME/attachments\" > {listing}\necho '{RESULT}'\n")
    answer_question(engine, owner="o", repo="r", question="What is on this screen?", context="",
                    images=[{"name": "leads page.png", "mime": "image/png", "data_b64": PNG},
                            {"name": "../../etc/passwd", "mime": "image/jpeg", "data_b64": PNG}])
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "attached 2 images" in prompt and "Read each one with the Read tool" in prompt
    assert "/attachments/1-leads-page.png" in prompt and "/attachments/2-passwd.jpg" in prompt
    assert sorted(listing.read_text().split()) == ["1-leads-page.png", "2-passwd.jpg"]
    # The checkout itself carries no attachment, and everything is gone afterwards.
    assert "r/attachments" not in prompt
    assert not list((tmp_path / "ws").iterdir())


def test_shape_mode_has_wider_budgets_and_the_same_read_only_tools(tmp_path):
    engine, out = engine_for(tmp_path)
    long_question = "Shape this. " * 400  # ~4 800 chars: over ask's 2 000, under shape's 12 000
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question=long_question, context="")
    assert e.value.status == 400 and "2000" in str(e.value)
    answer_question(engine, owner="o", repo="r", question=long_question, context="", mode="shape")
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--max-turns") + 1] == str(MODES["shape"][2])
    assert argv[argv.index("--allowedTools") + 1] == ASK_TOOLS
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="x", context="", mode="paint")
    assert e.value.status == 400


def test_a_bad_image_is_refused_before_anything_runs(tmp_path):
    engine, out = engine_for(tmp_path)
    for images, said in (
        ([{"name": "a.svg", "mime": "image/svg+xml", "data_b64": PNG}], "not supported"),
        ([{"name": "a.png", "mime": "image/png", "data_b64": "not base64!"}], "not valid base64"),
        ([{"name": "a.png", "mime": "image/png", "data_b64": PNG}] * 7, "At most 6"),
    ):
        with pytest.raises(AskError) as e:
            answer_question(engine, owner="o", repo="r", question="x", context="", images=images)
        assert e.value.status == 400 and said in str(e.value), said
    big = base64.b64encode(b"\x00" * (5 * 1024 * 1024 + 1)).decode()
    with pytest.raises(AskError) as e:
        check_images([{"name": "a.png", "mime": "image/png", "data_b64": big}])
    assert e.value.status == 400 and "over 5 MB" in str(e.value)
    assert not list(out.glob("prompt-*.txt"))


def test_an_ask_is_entered_in_the_ledger_as_a_finished_run(tmp_path):
    engine, _ = engine_for(tmp_path)
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    engine.ledger = Ledger(cfg.database_url)
    answer_question(engine, owner="o", repo="r", question="why?", context="", mode="shape")
    runs = engine.ledger.list_runs(repo="o/r")
    assert len(runs) == 1 and runs[0]["role"] == "ask" and runs[0]["outcome"] == "success"
    assert runs[0]["finished_at"] is not None
    assert not engine.ledger.list_runs(repo="o/r", active_only=True)
    import json
    assert json.loads(runs[0]["guards"])["usage"]["input_tokens"] == 120


async def test_the_endpoint_validates_images_and_passes_mode(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "A leads table.", "model": "m", "usage": {}}
    app.state.asker = asker
    h = {"authorization": "Bearer op-token"}
    body = {"owner": "o", "repo": "r", "question": "what is this?", "mode": "shape",
            "images": [{"name": "s.png", "mime": "image/png", "data_b64": PNG}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post("/ask", json=body, headers=h)
        assert ok.status_code == 200, ok.text
        bad = await c.post("/ask", json={**body, "images": [{"name": "s.svg", "mime": "image/svg+xml", "data_b64": PNG}]}, headers=h)
        assert bad.status_code == 400 and "not supported" in bad.json()["detail"]
        worse = await c.post("/ask", json={**body, "mode": "draw"}, headers=h)
        assert worse.status_code == 400
    assert seen["mode"] == "shape" and seen["images"][0]["name"] == "s.png"
