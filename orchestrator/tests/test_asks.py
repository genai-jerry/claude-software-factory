"""POST /asks: a question answered in the background, collected with GET /asks/{id}.

The caller is never held on an open request while Claude reads, so an answer
that takes longer than its HTTP client will wait is not lost; the job lives in
the ledger, a repeated submit does not run Claude twice, and a job a restart
interrupted says so.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import threading

import httpx
import sqlalchemy as sa

from factory_orchestrator.ask import AskError
from factory_orchestrator.config import load_config
from factory_orchestrator.ledger import Ledger, asks
from factory_orchestrator.webhook import ASK_INTERRUPTED, create_app

from .test_config import BASE

H = {"authorization": "Bearer op-token"}
BODY = {"owner": "o", "repo": "r", "question": "why?", "context": "thread", "mode": "shape"}


def _app(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    ledger = Ledger(cfg.database_url)
    return create_app(cfg, ledger, lambda *_: None, poll_interval=0.05), ledger


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _until_finished(c, ask_id):
    for _ in range(200):
        got = (await c.get(f"/asks/{ask_id}", headers=H)).json()
        if got["status"] != "running":
            return got
        await asyncio.sleep(0.01)
    raise AssertionError("the ask never finished")


async def test_an_ask_is_accepted_at_once_and_its_answer_collected_later(tmp_path):
    app, _ = _app(tmp_path)
    release = threading.Event()
    calls = []

    def asker(**kw):
        calls.append(kw)
        release.wait(5)
        return {"answer": "The reminder job ran twice.", "model": "m", "usage": {"input_tokens": 3},
                "session": "s-1", "resumed": False}
    app.state.asker = asker
    async with _client(app) as c:
        assert (await c.post("/asks", json={**BODY, "id": "a1"})).status_code == 401
        sent = await c.post("/asks", json={**BODY, "id": "a1"}, headers=H)
        # Answered while Claude is still working: nothing waits on the answer.
        assert sent.status_code == 202 and sent.json() == {"id": "a1", "status": "running"}
        assert (await c.get("/asks/a1")).status_code == 401
        assert (await c.get("/asks/a1", headers=H)).json()["status"] == "running"

        # The same id again starts nothing and reports the job as it stands.
        again = await c.post("/asks", json={**BODY, "id": "a1"}, headers=H)
        assert again.status_code == 200 and again.json()["status"] == "running"

        release.set()
        got = await _until_finished(c, "a1")
    assert got["status"] == "done" and got["answer"] == "The reminder job ran twice."
    assert got["model"] == "m" and got["session"] == "s-1" and got["usage"] == {"input_tokens": 3}
    assert got["finished_at"] is not None
    assert len(calls) == 1 and calls[0]["mode"] == "shape" and calls[0]["question"] == "why?"


async def test_a_failed_ask_carries_the_reason_and_the_status_ask_would_have_sent(tmp_path):
    app, _ = _app(tmp_path)

    def refuses(**_):
        raise AskError("You've hit the usage limit.", 429)

    def crashes(**_):
        raise RuntimeError("token ghs_secret in a path")
    async with _client(app) as c:
        app.state.asker = refuses
        await c.post("/asks", json={**BODY, "id": "limit"}, headers=H)
        limit = await _until_finished(c, "limit")
        app.state.asker = crashes
        await c.post("/asks", json={**BODY, "id": "crash"}, headers=H)
        crash = await _until_finished(c, "crash")
    assert limit == {**limit, "status": "failed", "error": "You've hit the usage limit.", "error_status": 429}
    assert crash["status"] == "failed" and crash["error_status"] == 500
    assert "RuntimeError" in crash["error"] and "ghs_secret" not in crash["error"]


async def test_a_bad_ask_is_refused_before_a_job_exists(tmp_path):
    app, ledger = _app(tmp_path)
    app.state.asker = lambda **_: {"answer": "x"}
    async with _client(app) as c:
        assert (await c.post("/asks", json=BODY, headers=H)).status_code == 400
        assert (await c.post("/asks", json={**BODY, "id": "../x"}, headers=H)).status_code == 400
        bad = await c.post("/asks", json={**BODY, "id": "b1", "mode": "draw"}, headers=H)
        assert bad.status_code == 400
        assert (await c.get("/asks/b1", headers=H)).status_code == 404
    assert ledger.get_ask("b1") is None


async def test_the_waiting_ask_still_answers(tmp_path):
    app, _ = _app(tmp_path)
    app.state.asker = lambda **_: {"answer": "Because of the cap.", "model": "m", "usage": {}}
    async with _client(app) as c:
        ok = await c.post("/ask", json=BODY, headers=H)
    assert ok.status_code == 200 and ok.json()["answer"] == "Because of the cap."


async def test_a_restart_fails_the_asks_it_interrupted_and_drops_old_ones(tmp_path):
    app, ledger = _app(tmp_path)
    ledger.start_ask("cut-off")
    ledger.start_ask("answered")
    ledger.finish_ask("answered", result={"answer": "yes"})
    ledger.start_ask("ancient")
    ledger.finish_ask("ancient", result={"answer": "old"})
    with ledger.engine.begin() as cx:
        cx.execute(asks.update().where(asks.c.id == "ancient")
                   .values(created_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=8)))

    await app.state.start_worker()
    try:
        for _ in range(100):
            if ledger.get_ask("cut-off")["status"] != "running":
                break
            await asyncio.sleep(0.01)
    finally:
        await app.state.stop_worker()
    cut = ledger.get_ask("cut-off")
    assert cut["status"] == "failed" and cut["error"] == ASK_INTERRUPTED and cut["error_status"] == 503
    assert ledger.get_ask("answered")["status"] == "done"
    assert ledger.get_ask("ancient") is None
    # A late finish from a thread that somehow outlived the restart does not
    # overwrite what the caller was already told.
    ledger.finish_ask("cut-off", result={"answer": "late"})
    assert ledger.get_ask("cut-off")["status"] == "failed"
    with ledger.engine.begin() as cx:
        assert cx.execute(sa.select(sa.func.count()).select_from(asks)).scalar() == 2
