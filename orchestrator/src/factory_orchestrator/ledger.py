"""Execution bookkeeping: webhook idempotency ledger and the run ledger.

This is bookkeeping, never truth — pipeline state lives on GitHub
(orchestration/engine-contract). The delivery ledger makes redelivered
webhooks no-ops and doubles as the work queue (a delivery row is claimed,
processed, and stamped), so a crash between ack and processing loses
nothing: pending rows are re-claimed on restart. The runs table is the
observability surface failure comments link to.

SQLAlchemy Core against DATABASE_URL: sqlite for single-repo installs and
tests, postgres in production. No ORM — five statements do not need one.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any

import sqlalchemy as sa

log = logging.getLogger("factory-orchestrator.ledger")

metadata = sa.MetaData()

deliveries = sa.Table(
    "webhook_deliveries", metadata,
    sa.Column("delivery_guid", sa.String(64), primary_key=True),
    sa.Column("event", sa.String(64), nullable=False),
    sa.Column("payload", sa.Text, nullable=False),
    sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("error", sa.Text),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("processed_at", sa.DateTime(timezone=True)),
)

#: Every `owner/repo` this engine has been handed a delivery for. The
#: reconciler sweeps these (orchestration/engine-contract): its whole job is
#: catching automatic steps that were missed while the process was down, and
#: `CLAIMED_REPOS` — the only sweep list before this — is optional, empty in
#: every shipped config, and silent when unset, so the sweep ran over nothing
#: and the one state where a lost delivery is terminal (an expedited task at
#: `factory:ready`) had no backstop at all. A repo the orchestrator has been
#: sent an event for is a repo it drives; that is the list.
repos_seen = sa.Table(
    "repos_seen", metadata,
    sa.Column("full_name", sa.String(200), primary_key=True),
    sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
)

runs = sa.Table(
    "runs", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("repo", sa.String(200), nullable=False),
    sa.Column("issue", sa.Integer, nullable=False),
    sa.Column("role", sa.String(40), nullable=False),
    sa.Column("trigger", sa.String(200), nullable=False),
    sa.Column("model", sa.String(100)),
    sa.Column("model_fallbacks", sa.Text),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("outcome", sa.String(20)),          # success | no_op | error | timeout
    sa.Column("guards", sa.Text),                  # JSON: snapshot/no-op guard details
    sa.Column("transcript_path", sa.Text),
    sa.Column("error", sa.Text),
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Ledger:
    def __init__(self, database_url: str):
        self.engine = sa.create_engine(database_url, future=True)
        metadata.create_all(self.engine)

    # -- deliveries -------------------------------------------------------
    def record_delivery(self, guid: str, event: str, payload: dict[str, Any]) -> bool:
        """Insert a delivery; False if the guid was already seen (redelivery)."""
        with self.engine.begin() as cx:
            try:
                cx.execute(deliveries.insert().values(
                    delivery_guid=guid, event=event,
                    payload=json.dumps(payload), received_at=_now()))
                fresh = True
            except sa.exc.IntegrityError:
                fresh = False
        # Outside the insert's transaction: a redelivery still proves the repo
        # is live, and a bookkeeping failure here must not lose the delivery.
        self.note_repo((payload.get("repository") or {}).get("full_name") or "")
        return fresh

    def note_repo(self, full_name: str) -> None:
        """Remember a repo this engine has seen work for. Never fails a caller.

        Called on every recorded delivery, which is the one funnel every way
        in shares (HMAC webhook, Console-forwarded event, operator dispatch).
        Bookkeeping, like the rest of this module: losing a row costs a sweep,
        never a state transition.
        """
        if not full_name or "/" not in full_name:
            return
        now = _now()
        try:
            with self.engine.begin() as cx:
                seen = cx.execute(repos_seen.update()
                                  .where(repos_seen.c.full_name == full_name)
                                  .values(last_seen_at=now)).rowcount
                if not seen:
                    cx.execute(repos_seen.insert().values(
                        full_name=full_name, first_seen_at=now, last_seen_at=now))
        except sa.exc.SQLAlchemyError:
            # Two processes can race the insert; the loser has nothing to do.
            log.debug("could not record %s in the sweep list", full_name, exc_info=True)

    def known_repos(self) -> list[str]:
        """Every repo recorded by `note_repo`, oldest first."""
        with self.engine.begin() as cx:
            return [r[0] for r in cx.execute(
                sa.select(repos_seen.c.full_name).order_by(repos_seen.c.first_seen_at))]

    def claim_pending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Atomically move up to `limit` pending deliveries to processing."""
        with self.engine.begin() as cx:
            rows = cx.execute(
                sa.select(deliveries.c.delivery_guid, deliveries.c.event, deliveries.c.payload)
                .where(deliveries.c.status == "pending")
                .order_by(deliveries.c.received_at).limit(limit)).fetchall()
            claimed = []
            for guid, event, payload in rows:
                n = cx.execute(deliveries.update()
                               .where(deliveries.c.delivery_guid == guid,
                                      deliveries.c.status == "pending")
                               .values(status="processing")).rowcount
                if n:
                    claimed.append({"guid": guid, "event": event, "payload": json.loads(payload)})
            return claimed

    def finish_delivery(self, guid: str, *, error: str | None = None) -> None:
        with self.engine.begin() as cx:
            cx.execute(deliveries.update().where(deliveries.c.delivery_guid == guid)
                       .values(status="failed" if error else "done",
                               error=error, processed_at=_now()))

    def get_delivery(self, guid: str) -> dict[str, Any] | None:
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(deliveries).where(deliveries.c.delivery_guid == guid)).mappings().first()
            return dict(row) if row else None

    def requeue_processing(self) -> int:
        """On startup: anything stuck in processing died with a prior process."""
        with self.engine.begin() as cx:
            return cx.execute(deliveries.update()
                              .where(deliveries.c.status == "processing")
                              .values(status="pending")).rowcount

    # -- runs -------------------------------------------------------------
    def start_run(self, *, repo: str, issue: int, role: str, trigger: str) -> str:
        run_id = str(uuid.uuid4())
        with self.engine.begin() as cx:
            cx.execute(runs.insert().values(
                id=run_id, repo=repo, issue=issue, role=role,
                trigger=trigger, started_at=_now()))
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Patch a live run (model, phase, transcript path) before finish_run."""
        if not fields:
            return
        with self.engine.begin() as cx:
            cx.execute(runs.update().where(runs.c.id == run_id).values(**fields))

    def finish_run(self, run_id: str, *, outcome: str, model: str | None = None,
                   model_fallbacks: list[str] | None = None,
                   guards: dict[str, Any] | None = None,
                   transcript_path: str | None = None, error: str | None = None) -> None:
        with self.engine.begin() as cx:
            cx.execute(runs.update().where(runs.c.id == run_id).values(
                outcome=outcome, model=model,
                model_fallbacks=json.dumps(model_fallbacks or []),
                guards=json.dumps(guards or {}),
                transcript_path=transcript_path, error=error, finished_at=_now()))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(runs).where(runs.c.id == run_id)).mappings().first()
            return dict(row) if row else None

    def list_runs(self, *, repo: str | None = None, issue: int | None = None,
                  active_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        q = sa.select(runs).order_by(runs.c.started_at.desc()).limit(limit)
        if repo:
            q = q.where(runs.c.repo == repo)
        if issue is not None:
            q = q.where(runs.c.issue == issue)
        if active_only:
            q = q.where(runs.c.finished_at.is_(None))
        with self.engine.begin() as cx:
            return [dict(r) for r in cx.execute(q).mappings()]
