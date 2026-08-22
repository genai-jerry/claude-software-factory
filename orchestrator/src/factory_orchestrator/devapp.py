"""Uvicorn app factory for local development: `scripts/dev.sh` runs
`uvicorn --factory factory_orchestrator.devapp:create --reload`."""

from __future__ import annotations

from .main import build_service


def create():
    _cfg, _ledger, _engine, app = build_service()
    return app
