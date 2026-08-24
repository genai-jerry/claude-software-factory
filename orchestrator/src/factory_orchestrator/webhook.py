"""FastAPI service: webhook intake, operator dispatch, run telemetry, health.

Intake contract (orchestration/langgraph-engine spec): verify the HMAC
signature → record in the idempotency ledger → 200 immediately. Processing
is asynchronous: a background worker claims pending deliveries from the
ledger (which doubles as a restart-safe queue) and hands each to the
processor callable — in production the LangGraph pipeline, in tests a stub.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from .config import Config
from .console_secrets import apply_runtime_agent_secrets
from .github_app import verify_signature
from .ledger import Ledger

log = logging.getLogger("factory-orchestrator")

Processor = Callable[[str, dict[str, Any]], None]
"""(event_name, payload) -> None. Raises to mark the delivery failed."""


def public_delivery_error(exc: BaseException) -> str:
    """Operator-facing text stamped on the ledger and shown by the Console."""
    name = type(exc).__name__
    text = str(exc)
    if name == "InvalidKeyError" or "Could not parse the provided public key" in text:
        return (
            "GitHub App private key is not a valid PEM. The orchestrator is using a "
            "placeholder (GITHUB_APP_ID=000000). The Console must send an installation "
            "token on /dispatch, or set a real GITHUB_APP_PRIVATE_KEY."
        )
    return f"{name}: {exc}"


def create_app(cfg: Config, ledger: Ledger, processor: Processor,
               *, poll_interval: float = 0.5) -> FastAPI:
    stop = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.start_worker()
        yield
        await app.state.stop_worker()

    app = FastAPI(title="factory-orchestrator", docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    app.state.cfg = cfg
    app.state.ledger = ledger
    app.state.processor = processor

    async def worker_loop() -> None:
        log.info("orchestrator worker started — GitHub events arrive at POST /webhooks/github and POST /events")
        requeued = ledger.requeue_processing()
        if requeued:
            log.info("requeued %d deliveries stuck in processing from a prior run", requeued)
        while not stop.is_set():
            batch = ledger.claim_pending()
            if not batch:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                except TimeoutError:
                    pass
                continue
            for item in batch:
                payload = item["payload"] if isinstance(item["payload"], dict) else {}
                repo = (payload.get("repository") or {}).get("full_name", "-")
                issue = (payload.get("issue") or {}).get("number")
                if issue is None:
                    issue = (payload.get("inputs") or {}).get("issue_number", "-")
                log.info(
                    "processing delivery=%s event=%s action=%s repo=%s issue=%s",
                    item["guid"], item["event"], payload.get("action", ""), repo, issue,
                )
                try:
                    # Processing runs in a thread: role runs block for minutes
                    # and must not stall the event loop or the intake endpoint.
                    await asyncio.to_thread(app.state.processor, item["event"], item["payload"])
                    ledger.finish_delivery(item["guid"])
                except Exception as exc:  # noqa: BLE001 - stamped on the ledger
                    log.exception("delivery %s failed", item["guid"])
                    ledger.finish_delivery(item["guid"], error=public_delivery_error(exc))

    async def start_worker() -> None:
        stop.clear()
        app.state.worker = asyncio.create_task(worker_loop())

    async def stop_worker() -> None:
        stop.set()
        await app.state.worker

    app.state.start_worker = start_worker
    app.state.stop_worker = stop_worker

    @app.get("/")
    async def root() -> dict[str, str]:
        # This is not the Factory Console. Hitting /api/* or /auth/* here is a
        # PUBLIC_ORIGIN / OAuth-callback mispoint — those belong on the Console.
        return {
            "service": "factory-orchestrator",
            "engine": cfg.engine_name,
            "health": "/healthz",
            "webhooks": "POST /webhooks/github",
            "events": "POST /events",
            "runs": "/runs",
        }

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "engine": cfg.engine_name}

    @app.post("/webhooks/github")
    async def github_webhook(request: Request) -> Response:
        body = await request.body()
        if not verify_signature(cfg.github_webhook_secret.reveal(), body,
                                request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=401, detail="bad signature")
        event = request.headers.get("x-github-event")
        guid = request.headers.get("x-github-delivery")
        if not event or not guid:
            raise HTTPException(status_code=400, detail="missing event headers")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        fresh = ledger.record_delivery(guid, event, payload)
        repo = (payload.get("repository") or {}).get("full_name", "-")
        issue = (payload.get("issue") or {}).get("number", "-")
        log.info(
            "webhook %s event=%s action=%s repo=%s issue=%s delivery=%s",
            "queued" if fresh else "duplicate",
            event, payload.get("action", ""), repo, issue, guid,
        )
        return Response(status_code=202 if fresh else 200,
                        content=json.dumps({"queued": fresh}),
                        media_type="application/json")

    def _require_dispatch_token(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        expected = cfg.dispatch_token.reveal()
        if not expected or auth != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="dispatch token required")

    @app.post("/events")
    async def github_event(request: Request) -> dict[str, Any]:
        """Console-forwarded GitHub event — same queue as HMAC webhooks.

        The Console App's hook URL is PUBLIC_ORIGIN, so `issues` labelled
        `factory:fast-track` never hit POST /webhooks/github. The Console
        worker (and the epic Start factory run button) POST here instead.
        Agent tokens are applied in-process and are not stored on the ledger.
        """
        _require_dispatch_token(request)
        body = await request.json()
        event = body.get("event")
        payload = body.get("payload")
        guid = body.get("delivery_guid")
        if not event or not isinstance(payload, dict) or not guid:
            raise HTTPException(status_code=400,
                                detail="event, payload, and delivery_guid are required")
        applied = apply_runtime_agent_secrets(cfg, body)
        queued_payload = dict(payload)
        token = body.get("github_token")
        if isinstance(token, str) and token:
            inputs = dict(queued_payload.get("inputs") or {})
            inputs["github_token"] = token
            queued_payload["inputs"] = inputs
        fresh = ledger.record_delivery(str(guid), str(event), queued_payload)
        repo = (queued_payload.get("repository") or {}).get("full_name", "-")
        issue = (queued_payload.get("issue") or {}).get("number", "-")
        log.info(
            "event %s event=%s action=%s repo=%s issue=%s delivery=%s token=%s agent=%s",
            "queued" if fresh else "duplicate",
            event, queued_payload.get("action", ""), repo, issue, guid,
            "yes" if token else "no",
            ",".join(applied) or "none",
        )
        return {"queued": fresh, "delivery_guid": guid}

    @app.post("/dispatch")
    async def dispatch(request: Request) -> dict[str, Any]:
        """Operator entry point — the manual "Run workflow" equivalent."""
        _require_dispatch_token(request)
        body = await request.json()
        for key in ("owner", "repo", "role", "issue"):
            if not body.get(key):
                raise HTTPException(status_code=400, detail=f"missing {key}")
        # Synthesized as a workflow_dispatch-shaped delivery through the same
        # idempotent queue as real webhooks; guid is caller-supplied or random.
        import uuid
        guid = body.get("dispatch_id") or f"dispatch-{uuid.uuid4()}"
        inputs: dict[str, Any] = {"role": body["role"], "issue_number": str(body["issue"])}
        if body.get("github_token"):
            inputs["github_token"] = body["github_token"]
        applied = apply_runtime_agent_secrets(cfg, body)
        payload = {"action": "dispatch",
                   "repository": {"full_name": f"{body['owner']}/{body['repo']}",
                                  "owner": {"login": body["owner"]}, "name": body["repo"]},
                   "inputs": inputs}
        fresh = ledger.record_delivery(guid, "workflow_dispatch", payload)
        log.info("dispatch queued=%s role=%s repo=%s/%s issue=%s id=%s token=%s agent=%s",
                 fresh, body["role"], body["owner"], body["repo"], body["issue"], guid,
                 "yes" if body.get("github_token") else "no",
                 ",".join(applied) or "none")
        return {"queued": fresh, "dispatch_id": guid}

    @app.get("/deliveries/{guid}")
    async def get_delivery(guid: str, request: Request) -> dict[str, Any]:
        """Console poll target: a /dispatch 200 is only 'queued', not 'done'."""
        _require_dispatch_token(request)
        row = ledger.get_delivery(guid)
        if not row:
            raise HTTPException(status_code=404, detail="no such delivery")
        return {
            "id": row["delivery_guid"],
            "event": row["event"],
            "status": row["status"],
            "error": row.get("error"),
            "received_at": str(row["received_at"]) if row.get("received_at") is not None else None,
            "processed_at": str(row["processed_at"]) if row.get("processed_at") is not None else None,
        }

    @app.get("/runs")
    async def list_runs(repo: str | None = None, issue: int | None = None,
                        active: bool = False) -> list[dict[str, Any]]:
        return [_public_run(r) for r in ledger.list_runs(repo=repo, issue=issue,
                                                         active_only=active)]

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = ledger.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="no such run")
        return _public_run(run)

    @app.get("/runs/{run_id}/transcript")
    async def get_transcript(run_id: str) -> Response:
        run = ledger.get_run(run_id)
        if not run or not run.get("transcript_path"):
            raise HTTPException(status_code=404, detail="no transcript")
        try:
            with open(run["transcript_path"], encoding="utf-8") as fh:
                return Response(content=fh.read(), media_type="text/plain")
        except OSError as exc:
            raise HTTPException(status_code=404, detail="transcript unavailable") from exc

    return app


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    out = dict(run)
    for key in ("model_fallbacks", "guards"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    for key in ("started_at", "finished_at"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    out.pop("transcript_path", None)  # served via /transcript, path is internal
    out["status"] = "completed" if out.get("finished_at") else "running"
    if not out.get("outcome"):
        out["outcome"] = "running"
    return out
