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

        r = await client.get("/runs", params={"repo": "o/r", "active": "true"})
        assert [x["id"] for x in r.json()] == [active_id]
        assert r.json()[0]["role"] == "planner"

        r = await client.get(f"/runs/{run_id}")
        assert r.json()["guards"] == {"trace": True}

        r = await client.get(f"/runs/{run_id}/transcript")
        assert r.status_code == 200 and "role output" in r.text

        r = await client.get(f"/runs/{active_id}/transcript")
        assert r.status_code == 404
        r = await client.get("/runs/nope")
        assert r.status_code == 404

    await with_client(app, go)
