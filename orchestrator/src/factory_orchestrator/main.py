"""Service entry point: wire config, ledger, graph, webhook app; run uvicorn.

LangSmith tracing needs no code: set LANGSMITH_TRACING=true and
LANGSMITH_API_KEY in the environment and langgraph picks them up.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from .config import load_config
from .github_app import GitHubApp
from .graph import Engine, Processor, build_graph, make_checkpointer
from .ledger import Ledger
from .models import default_probe
from .reconcile import sweep_repo
from .role_runner import FactorySource, RoleRunner
from .webhook import create_app

log = logging.getLogger("factory-orchestrator")


def build_service():
    cfg = load_config()
    ledger = Ledger(cfg.database_url)
    app = GitHubApp(cfg)
    source = FactorySource(cfg, local_path=os.environ.get("FACTORY_LOCAL_PATH"))
    runner = RoleRunner(cfg, source)
    engine = Engine(cfg, ledger, app, runner, default_probe(cfg),
                    transcript_dir=os.environ.get("TRANSCRIPT_DIR"))
    graph = build_graph(engine, checkpointer=make_checkpointer(cfg.database_url))
    processor = Processor(engine, graph)
    return cfg, ledger, engine, create_app(cfg, ledger, processor)


def start_reconciler(engine, ledger, interval_seconds: int = 900) -> threading.Thread:
    repos_env = os.environ.get("CLAIMED_REPOS", "")
    repos = [r.strip() for r in repos_env.split(",") if "/" in r]

    def loop() -> None:
        while True:
            for full in repos:
                owner, repo = full.split("/", 1)
                try:
                    sweep_repo(engine.port(owner, repo), ledger)
                except Exception:  # noqa: BLE001
                    log.exception("reconcile sweep failed for %s", full)
            time.sleep(interval_seconds)

    t = threading.Thread(target=loop, daemon=True, name="reconciler")
    t.start()
    return t


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    cfg, ledger, engine, app = build_service()
    start_reconciler(engine, ledger)
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
