import asyncio
import json

import httpx
import pytest

from factory_orchestrator.config import load_config
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.webhook import create_app
from .test_config import BASE
from .test_github_app import sign

SECRET = BASE["GITHUB_WEBHOOK_SECRET"]


@pytest.fixture
def service(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db",
                       "DISPATCH_TOKEN": "op-token"})
    ledger = Ledger(cfg.database_url)
    processed = []
    app = create_app(cfg, ledger, lambda ev, payload: processed.append((ev, payload)),
                     poll_interval=0.05)
    return cfg, ledger, processed, app


async def post_event(client, guid, body=b'{"action": "opened"}', secret=SECRET):
    return await client.post("/webhooks/github", content=body, headers={
        "x-hub-signature-256": sign(secret, body),
        "x-github-event": "issues",
        "x-github-delivery": guid,
    })


async def with_client(app, fn):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as client:
        # ASGITransport does not drive the lifespan; start the worker by hand.
        await app.state.start_worker()
        try:
            return await fn(client)
        finally:
            await app.state.stop_worker()


async def test_bad_signature_rejected(service):
    _, ledger, processed, app = service
    async def go(client):
        r = await client.post("/webhooks/github", content=b"{}", headers={
            "x-hub-signature-256": "sha256=deadbeef",
            "x-github-event": "issues", "x-github-delivery": "g1"})
        assert r.status_code == 401
    await with_client(app, go)
    assert not processed


async def test_missing_headers_rejected(service):
    *_, app = service
    async def go(client):
        body = b"{}"
        r = await client.post("/webhooks/github", content=body,
                              headers={"x-hub-signature-256": sign(SECRET, body)})
        assert r.status_code == 400
    await with_client(app, go)


async def test_delivery_processed_and_redelivery_noop(service):
    _, ledger, processed, app = service
    async def go(client):
        r1 = await post_event(client, "guid-1")
        assert r1.status_code == 202 and r1.json() == {"queued": True}
        for _ in range(100):
            await asyncio.sleep(0.02)
            if processed:
                break
        assert processed == [("issues", {"action": "opened"})]
        r2 = await post_event(client, "guid-1")
        assert r2.status_code == 200 and r2.json() == {"queued": False}
        await asyncio.sleep(0.1)
        assert len(processed) == 1
    await with_client(app, go)


async def test_processor_failure_stamped(service):
    cfg, ledger, _, _ = service
    def boom(ev, payload):
        raise RuntimeError("kaput")
    app = create_app(cfg, ledger, boom, poll_interval=0.05)
    async def go(client):
        await post_event(client, "guid-err")
        for _ in range(100):
            await asyncio.sleep(0.02)
            rows = ledger.claim_pending()
            assert rows == []
            with ledger.engine.begin() as cx:
                import sqlalchemy as sa
                from factory_orchestrator.ledger import deliveries
                row = cx.execute(sa.select(deliveries.c.status, deliveries.c.error)
                                 .where(deliveries.c.delivery_guid == "guid-err")).first()
            if row and row[0] == "failed":
                assert "kaput" in row[1]
                return
        raise AssertionError("delivery never stamped failed")
    await with_client(app, go)


async def test_requeue_on_restart(service):
    cfg, ledger, processed, app = service
    ledger.record_delivery("stuck", "issues", {"action": "opened"})
    assert ledger.claim_pending()  # simulate a crash mid-processing
    assert ledger.requeue_processing() == 1
    claimed = ledger.claim_pending()
    assert [c["guid"] for c in claimed] == ["stuck"]


async def test_dispatch_requires_token(service):
    *_, app = service
    async def go(client):
        r = await client.post("/dispatch", json={"owner": "o", "repo": "r",
                                                 "role": "reviewer", "issue": 12})
        assert r.status_code == 401
        r = await client.post("/dispatch", json={"owner": "o", "repo": "r",
                                                 "role": "reviewer", "issue": 12},
                              headers={"authorization": "Bearer op-token"})
        assert r.status_code == 200 and r.json()["queued"] is True
    await with_client(app, go)


async def test_health(service):
    *_, app = service
    async def go(client):
        r = await client.get("/healthz")
        assert r.status_code == 200 and r.json()["engine"] == "langgraph"
    await with_client(app, go)
