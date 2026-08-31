import httpx

from factory_orchestrator.config import load_config
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.webhook import create_app

from .test_config import BASE
from .test_webhook import with_client


async def test_runs_surface(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    ledger = Ledger(cfg.database_url)
    transcript = tmp_path / "t.log"
    transcript.write_text("role output, secrets already ***")
    run_id = ledger.start_run(repo="o/r", issue=5, role="intake", trigger="issues:opened")
    active_id = ledger.start_run(repo="o/r", issue=6, role="planner", trigger="issues:labeled")
    ledger.finish_run(run_id, outcome="success", model="claude-sonnet-5",
                      model_fallbacks=["claude-opus-5"],
                      guards={"trace": True}, transcript_path=str(transcript))
    app = create_app(cfg, ledger, lambda e, p: None, poll_interval=0.05)

    async def go(client: httpx.AsyncClient):
        r = await client.get("/runs", params={"repo": "o/r"})
        assert r.status_code == 200
        runs = r.json()
        assert {x["id"] for x in runs} == {run_id, active_id}
        done = next(x for x in runs if x["id"] == run_id)
        assert done["outcome"] == "success"
        assert done["model_fallbacks"] == ["claude-opus-5"]
        assert "transcript_path" not in done  # internal path never leaves the service
        assert done["events"] == []

        r = await client.get("/runs", params={"repo": "o/r", "active": "true"})
        assert [x["id"] for x in r.json()] == [active_id]
        assert r.json()[0]["role"] == "planner"
        assert r.json()[0]["status"] == "running"
        assert r.json()[0]["outcome"] == "running"

        r = await client.get(f"/runs/{run_id}")
        assert r.json()["guards"] == {"trace": True}

        r = await client.get(f"/runs/{run_id}/transcript")
        assert r.status_code == 200 and "role output" in r.text

        r = await client.get(f"/runs/{active_id}/transcript")
        assert r.status_code == 404
        r = await client.get("/runs/nope")
        assert r.status_code == 404

    await with_client(app, go)


async def test_update_run_exposes_model_while_live(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    ledger = Ledger(cfg.database_url)
    run_id = ledger.start_run(repo="o/r", issue=5, role="profiler", trigger="dispatch")
    ledger.update_run(run_id, model="claude-opus-5", outcome="running",
                      guards='{"phase": "running Claude (claude-opus-5)"}')
    app = create_app(cfg, ledger, lambda e, p: None, poll_interval=0.05)

    async def go(client: httpx.AsyncClient):
        r = await client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "claude-opus-5"
        assert body["outcome"] == "running"
        assert body["status"] == "running"
        assert body["guards"]["phase"] == "running Claude (claude-opus-5)"
        assert body["finished_at"] is None
        assert body["events"] == []
    await with_client(app, go)


async def test_run_json_includes_event_log(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    ledger = Ledger(cfg.database_url)
    transcript = tmp_path / "t.log"
    transcript.write_text("partial output\n")
    (tmp_path / "t.events.jsonl").write_text(
        '{"ts":"2026-08-28T03:00:00+00:00","kind":"phase","message":"waiting for tests"}\n'
        '{"ts":"2026-08-28T03:00:01+00:00","kind":"phase","message":"pushing the branch"}\n'
    )
    run_id = ledger.start_run(repo="o/r", issue=5, role="fasttrack", trigger="labeled")
    ledger.update_run(run_id, outcome="running",
                      guards='{"phase": "waiting for tests"}',
                      transcript_path=str(transcript))
    app = create_app(cfg, ledger, lambda e, p: None, poll_interval=0.05)

    async def go(client: httpx.AsyncClient):
        r = await client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "running"
        assert [e["message"] for e in body["events"]] == [
            "waiting for tests", "pushing the branch"]
        assert "transcript_path" not in body
    await with_client(app, go)


async def test_a_browser_gets_a_page_not_json(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    ledger = Ledger(cfg.database_url)
    run_id = ledger.start_run(repo="o/r", issue=7, role="implementer", trigger="labeled")
    ledger.finish_run(run_id, outcome="success", model="claude-opus-5")
    app = create_app(cfg, ledger, lambda e, p: None, poll_interval=0.05)

    async def go(client: httpx.AsyncClient):
        browser = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
        r = await client.get(f"/runs/{run_id}", headers=browser)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "Factory run" in r.text and "o/r" in r.text and "implementer" in r.text
        # a run link with a marked-up repo name must not break out of the page
        assert "<script" not in r.text.lower()

        r = await client.get("/runs", headers=browser)
        assert r.headers["content-type"].startswith("text/html")
        assert f"/runs/{run_id}" in r.text

        # API callers (the Console proxy among them) still get JSON
        r = await client.get(f"/runs/{run_id}")
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["outcome"] == "success"

    await with_client(app, go)
