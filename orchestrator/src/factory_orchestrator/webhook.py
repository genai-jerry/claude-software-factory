"""FastAPI service: webhook intake, operator dispatch, run telemetry, health.

Intake contract (orchestration/langgraph-engine spec): verify the HMAC
signature → record in the idempotency ledger → 200 immediately. Processing
is asynchronous: a background worker claims pending deliveries from the
ledger (which doubles as a restart-safe queue) and hands each to the
processor callable — in production the LangGraph pipeline, in tests a stub.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from .config import Config
from .console_secrets import apply_runtime_agent_secrets
from .github_app import verify_signature
from .ledger import Ledger
from .live_log import read_events
from .usage import summarize

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


def _carry_refresh(inputs: dict[str, Any], console_url: Any, installation_id: Any) -> None:
    """Record how to re-mint this repo's GitHub token, when the caller said.

    Both halves are needed to call the Console's mint endpoint, so a partial
    pair is no better than none and is dropped rather than half-stored.
    """
    if not console_url or not installation_id:
        return
    try:
        inputs["installation_id"] = int(installation_id)
    except (TypeError, ValueError):
        return
    inputs["console_url"] = str(console_url)


#: What a caller is told about an ask that was running when the process stopped.
ASK_INTERRUPTED = "The orchestrator restarted while answering. Ask again."


def _public_ask(row: dict[str, Any]) -> dict[str, Any]:
    """An asks row as GET /asks/{id} returns it: the answer's fields at the top."""
    out: dict[str, Any] = json.loads(row["result"]) if row.get("result") else {}
    out.update(id=row["id"], status=row["status"])
    if row.get("error"):
        out["error"] = row["error"]
        out["error_status"] = row.get("error_status")
    for key in ("created_at", "finished_at"):
        out[key] = str(row[key]) if row.get(key) is not None else None
    return out


def thread_key(payload: dict[str, Any]) -> str:
    """The issue a delivery belongs to — the same key as the graph's thread."""
    repo = (payload.get("repository") or {}).get("full_name", "unknown/unknown")
    issue = (payload.get("issue") or {}).get("number")
    if issue is None:
        issue = (payload.get("inputs") or {}).get("issue_number", "repo")
    return f"{repo}#{issue}"


def create_app(cfg: Config, ledger: Ledger, processor: Processor,
               *, poll_interval: float = 0.5, concurrency: int = 8) -> FastAPI:
    stop = asyncio.Event()
    # Deliveries for different issues run side by side; deliveries for one
    # issue run in the order they arrived. One graph invocation can hold its
    # delivery for hours (an expedited epic walks every stage inside it), and
    # a single serial worker left every other issue's events queued behind
    # it — a reply on a blocked task waited for someone else's release run.
    # Role runs are capped separately, by RoleRunner's max_parallel slots.
    slots = asyncio.Semaphore(max(1, concurrency))
    issue_locks: dict[str, asyncio.Lock] = {}
    waiting: dict[str, int] = {}  # deliveries holding or queued on each lock
    inflight: set[asyncio.Task] = set()

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
    app.state.asker = None  # set by main.build_service; tests may set a stub

    async def worker_loop() -> None:
        log.info("orchestrator worker started — GitHub events arrive at POST /webhooks/github and POST /events")
        requeued = ledger.requeue_processing()
        if requeued:
            log.info("requeued %d deliveries stuck in processing from a prior run", requeued)
        lost = ledger.interrupt_asks(ASK_INTERRUPTED)
        if lost:
            log.info("failed %d asks a prior run left unanswered", lost)
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
                key = thread_key(payload)
                # Taken here, in claim order, so one issue's deliveries queue
                # on its lock in the order they arrived (asyncio.Lock is FIFO).
                lock = issue_locks.setdefault(key, asyncio.Lock())
                waiting[key] = waiting.get(key, 0) + 1
                task = asyncio.create_task(process(item, payload, key, lock))
                inflight.add(task)
                task.add_done_callback(inflight.discard)
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)

    async def process(item: dict[str, Any], payload: dict[str, Any], key: str,
                      lock: asyncio.Lock) -> None:
        async with lock, slots:
            log.info(
                "processing delivery=%s event=%s action=%s thread=%s",
                item["guid"], item["event"], payload.get("action", ""), key,
            )
            try:
                # Processing runs in a thread: role runs block for minutes
                # and must not stall the event loop or the intake endpoint.
                await asyncio.to_thread(app.state.processor, item["event"], item["payload"])
                ledger.finish_delivery(item["guid"])
            except Exception as exc:  # noqa: BLE001 - stamped on the ledger
                log.exception("delivery %s failed", item["guid"])
                ledger.finish_delivery(item["guid"], error=public_delivery_error(exc))
        waiting[key] -= 1
        if not waiting[key]:  # nothing else queued for this issue: drop its lock
            del waiting[key]
            issue_locks.pop(key, None)

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
        # This is not the Compass. Hitting /api/* or /auth/* here is a
        # PUBLIC_ORIGIN / OAuth-callback mispoint — those belong on the Console.
        return {
            "service": "factory-orchestrator",
            "engine": cfg.engine_name,
            "health": "/healthz",
            "webhooks": "POST /webhooks/github",
            "events": "POST /events",
            "runs": "/runs",
            "environments": "/environments",
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
        inputs = dict(queued_payload.get("inputs") or {})
        if isinstance(token, str) and token:
            inputs["github_token"] = token
            if body.get("github_token_expires_at"):
                inputs["github_token_expires_at"] = str(body["github_token_expires_at"])
        # Where that token can be re-minted when a long role outlives it. The
        # installation id rides on the GitHub payload itself for real deliveries.
        installation_id = body.get("installation_id") or (
            payload.get("installation") or {}).get("id")
        _carry_refresh(inputs, body.get("console_url"), installation_id)
        if inputs:
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

    def _ask_kwargs(body: dict[str, Any]) -> dict[str, Any]:
        """Check an ask request and turn it into the asker's arguments.

        Done before a slot or a clone is spent, for /ask and /asks alike.
        """
        if not isinstance(body.get("question"), str) or not body["question"].strip():
            raise HTTPException(status_code=400, detail="missing question")
        for key in ("owner", "repo"):
            if body.get(key) is not None and not isinstance(body.get(key), str):
                raise HTTPException(status_code=400, detail=f"{key} must be a string")
        if app.state.asker is None:
            raise HTTPException(status_code=501, detail="this orchestrator cannot answer questions")
        apply_runtime_agent_secrets(cfg, body)
        from .ask import CONVERSATION_KEY, MODES, AskError, check_images, check_repos
        mode = body.get("mode") or "ask"
        if mode not in MODES:
            raise HTTPException(status_code=400, detail="mode must be ask or shape")
        # Shape about a new product sends neither: no repository yet.
        owner, repo = str(body.get("owner") or ""), str(body.get("repo") or "")
        if bool(owner) != bool(repo):
            raise HTTPException(status_code=400, detail="send owner and repo together, or neither")
        images = body.get("images")
        repos = body.get("repos")
        conversation = body.get("conversation")
        if conversation is not None and (not isinstance(conversation, str)
                                         or not CONVERSATION_KEY.match(conversation)):
            raise HTTPException(status_code=400,
                                detail="conversation must match [A-Za-z0-9_-]{1,64}")
        session = body.get("session")
        if session is not None and (not isinstance(session, str) or not session.strip() or len(session) > 128):
            raise HTTPException(status_code=400, detail="session must be a short string")
        try:
            if images is not None:
                check_images(images)
            if repos is not None:
                check_repos(repos, owner, repo)
        except AskError as e:
            raise HTTPException(status_code=e.status, detail=str(e)) from e
        return dict(
            owner=owner, repo=repo,
            question=body["question"], context=str(body.get("context") or ""),
            branch=body.get("branch") if isinstance(body.get("branch"), str) else None,
            instructions=body.get("instructions") if isinstance(body.get("instructions"), str) else None,
            images=images if isinstance(images, list) else None, mode=mode,
            repos=repos if isinstance(repos, list) else None,
            conversation=conversation, session=session,
            mcp_servers=body.get("mcp_servers") if isinstance(body.get("mcp_servers"), list) else None)

    def _ask_failure(e: Exception, kwargs: dict[str, Any]) -> tuple[str, int]:
        """The reason and status an ask failed with, safe to hand the caller."""
        from .ask import AskError
        if isinstance(e, AskError):
            return str(e), e.status
        # The message can carry a token or a path; the kind of failure is
        # what the person needs, and the log has the rest.
        log.error("ask: unexpected failure for %s/%s", kwargs["owner"], kwargs["repo"], exc_info=e)
        return (f"The orchestrator failed while answering ({type(e).__name__}). "
                "Its log has the details.", 500)

    @app.post("/ask")
    async def ask(request: Request) -> dict[str, Any]:
        """A person's question, answered while the caller waits (ask.py).

        Kept for callers that have not moved to POST /asks. An answer can take
        minutes and nothing is sent until it is done, so a caller's HTTP
        client may give up first; /asks does not hold a request open.
        """
        _require_dispatch_token(request)
        kwargs = _ask_kwargs(await request.json())
        try:
            return await asyncio.to_thread(app.state.asker, **kwargs)
        except Exception as e:  # noqa: BLE001 - the asker deserves a reason, not a bare 500
            detail, status = _ask_failure(e, kwargs)
            raise HTTPException(status_code=status, detail=detail) from e

    ask_jobs: set[asyncio.Task] = set()  # held so a running ask is not collected

    async def _answer_in_background(ask_id: str, kwargs: dict[str, Any]) -> None:
        try:
            result = await asyncio.to_thread(app.state.asker, **kwargs)
        except Exception as e:  # noqa: BLE001 - stamped on the ask, for its caller
            detail, status = _ask_failure(e, kwargs)
            ledger.finish_ask(ask_id, error=detail, error_status=status)
            return
        ledger.finish_ask(ask_id, result=result)

    @app.post("/asks", status_code=202)
    async def submit_ask(request: Request, response: Response) -> dict[str, Any]:
        """Start answering a question in the background; poll GET /asks/{id}.

        The caller picks `id`. Sending an id that was seen before starts
        nothing and returns that ask as it stands (200), so a retried submit
        never runs Claude twice. A bad request is refused here, before any
        work, with the same checks and statuses as /ask.
        """
        _require_dispatch_token(request)
        body = await request.json()
        from .ask import CONVERSATION_KEY
        ask_id = body.get("id")
        if not isinstance(ask_id, str) or not CONVERSATION_KEY.match(ask_id):
            raise HTTPException(status_code=400, detail="id must match [A-Za-z0-9_-]{1,64}")
        kwargs = _ask_kwargs(body)
        seen = ledger.start_ask(ask_id)
        if seen is not None:
            response.status_code = 200
            return _public_ask(seen)
        job = asyncio.create_task(_answer_in_background(ask_id, kwargs))
        ask_jobs.add(job)
        job.add_done_callback(ask_jobs.discard)
        return {"id": ask_id, "status": "running"}

    @app.get("/asks/{ask_id}")
    async def get_ask(ask_id: str, request: Request) -> dict[str, Any]:
        """An ask's status, and its answer or the reason it failed once finished."""
        _require_dispatch_token(request)
        row = ledger.get_ask(ask_id)
        if not row:
            raise HTTPException(status_code=404, detail="no such ask")
        return _public_ask(row)

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
            if body.get("github_token_expires_at"):
                inputs["github_token_expires_at"] = str(body["github_token_expires_at"])
        # The Console already sends these; keeping them is what lets a role
        # that outlives its dispatch token get a new one instead of a 401.
        _carry_refresh(inputs, body.get("console_url"), body.get("installation_id"))
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
    async def list_runs(request: Request, repo: str | None = None,
                        issue: int | None = None, active: bool = False) -> Response:
        rows = [_public_run(r) for r in ledger.list_runs(repo=repo, issue=issue,
                                                         active_only=active)]
        if _wants_html(request):
            return Response(content=_runs_index_html(rows), media_type="text/html")
        return Response(content=json.dumps(rows), media_type="application/json")

    @app.get("/environments")
    async def environments() -> dict[str, Any]:
        """The build environments, who holds each and who waits (issue_workspaces.py)."""
        source = getattr(app.state, "environments", None)
        if source is None:
            return {"sessions": None, "environments": []}
        return await asyncio.to_thread(source)

    @app.get("/usage")
    async def usage() -> dict[str, Any]:
        """The last five hours of Claude use and any limit in force (usage.py)."""
        return summarize(ledger)

    @app.get("/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> Response:
        run = ledger.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="no such run")
        out = _public_run(run)
        if _wants_html(request):
            return Response(content=_run_html(out), media_type="text/html")
        return Response(content=json.dumps(out), media_type="application/json")

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


def _clock(value: Any) -> str:
    """A run's clock as ISO 8601 with its zone written, always UTC.

    The ledger stores an aware datetime, but SQLite hands it back naive
    (``2026-11-05 06:01:48.213069``), and a browser reads a bare timestamp
    as local time: a run four minutes old showed as "running for 334 min"
    in Compass five and a half hours east of Greenwich.
    """
    if isinstance(value, dt.datetime):
        at = value
    else:
        try:
            at = dt.datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.UTC)
    return at.astimezone(dt.UTC).isoformat()


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
            out[key] = _clock(out[key])
    out["events"] = read_events(out.get("transcript_path"))
    # Whether /transcript has anything to serve: the file lives in TRANSCRIPT_DIR,
    # which a redeploy can clear, so a past run's list entry says so rather than
    # linking to a log that is gone.
    path = out.pop("transcript_path", None)  # served via /transcript, path is internal
    out["has_log"] = bool(path) and Path(path).is_file()
    out["status"] = "completed" if out.get("finished_at") else "running"
    if not out.get("outcome"):
        out["outcome"] = "running"
    return out


def _wants_html(request: Request) -> bool:
    """A browser navigation sends Accept: text/html; API callers (including the
    Console's same-origin proxy) do not — they keep getting JSON."""
    return "text/html" in request.headers.get("accept", "")


_PAGE_CSS = (
    "body{margin:0;padding:2rem;background:#101418;color:#e6e8ea;"
    "font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}"
    "h1{font-size:1.1rem;margin:0 0 1rem}a{color:#7cb7ff}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{text-align:left;padding:.25rem .75rem .25rem 0;vertical-align:top}"
    "th{color:#9aa3ab;font-weight:normal;white-space:nowrap}"
    ".muted{color:#9aa3ab}.err{color:#ff8f8f}"
    "ol{padding-left:1.25rem}li{margin:.15rem 0}"
)


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _run_html(run: dict[str, Any]) -> str:
    """Human fallback for a browser opening the orchestrator's run link
    directly. The Compass is the real page for this run; this one
    exists so a raw link is never a wall of JSON."""
    running = run.get("status") == "running"
    refresh = '<meta http-equiv="refresh" content="5">' if running else ""
    fields = [("repo", run.get("repo")), ("issue", run.get("issue")),
              ("role", run.get("role")), ("trigger", run.get("trigger")),
              ("model", run.get("model")), ("started", run.get("started_at")),
              ("finished", run.get("finished_at")), ("outcome", run.get("outcome"))]
    rows = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>"
                   for k, v in fields if v not in (None, ""))
    error = (f'<p class="err">{_esc(run.get("error"))}</p>' if run.get("error") else "")
    events = "".join(
        f'<li><span class="muted">{_esc(e.get("ts"))}</span> '
        f"[{_esc(e.get('kind'))}] {_esc(e.get('message'))}</li>"
        for e in (run.get("events") or []))
    live = '<p class="muted">Run is live — this page refreshes every 5 seconds.</p>' if running else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8">{refresh}'
        f'<title>Factory run {_esc(run.get("id"))}</title><style>{_PAGE_CSS}</style></head>'
        f'<body><h1>Factory run · {_esc(run.get("role"))} · {_esc(run.get("repo"))}'
        f'#{_esc(run.get("issue"))}</h1>'
        f"<table>{rows}</table>{error}{live}"
        f"<h1>Events</h1><ol>{events or '<li class=muted>none yet</li>'}</ol>"
        f'<p><a href="/runs/{_esc(run.get("id"))}/transcript">Full transcript</a> · '
        f'<a href="/runs">All runs</a></p></body></html>'
    )


def _runs_index_html(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<tr><td><a href="/runs/{_esc(r.get("id"))}">{_esc(str(r.get("id"))[:8])}</a></td>'
        f'<td>{_esc(r.get("repo"))}#{_esc(r.get("issue"))}</td><td>{_esc(r.get("role"))}</td>'
        f'<td>{_esc(r.get("outcome"))}</td><td class="muted">{_esc(r.get("started_at"))}</td></tr>'
        for r in rows)
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>Factory runs</title>'
        f"<style>{_PAGE_CSS}</style></head><body><h1>Factory runs</h1>"
        f"<table><tr><th>run</th><th>issue</th><th>role</th><th>outcome</th><th>started</th></tr>"
        f"{body or '<tr><td class=muted colspan=5>no runs yet</td></tr>'}</table></body></html>"
    )
