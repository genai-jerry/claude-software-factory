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
from .console_secrets import (
    ConsoleSecretStore,
    apply_console_secrets,
    refresh_console_secrets,
)
from .github_app import GitHubApp
from .graph import Engine, Processor, build_graph, make_checkpointer
from .ledger import Ledger
from .models import default_probe
from .reconcile import sweep_repo
from .role_runner import FactorySource, RoleRunner
from .token_refresh import ConsoleTokenSource
from .webhook import create_app

log = logging.getLogger("factory-orchestrator")


def build_service():
    # Uvicorn --factory (devapp.create) never runs main(), so INFO logs from
    # the graph / runner / webhook worker would otherwise stay silent.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=False,
    )
    # Agent secrets may live in the Factory Console's store (set through its
    # UI, sealed in its database). Environment variables always win; the
    # store fills what the deployment left unset, and those values are
    # refreshed on the reconciler timer so a rotation in the Console reaches
    # role runs without a redeploy.
    env = dict(os.environ)
    console_store = None
    from_console: set[str] = set()
    if env.get("CONSOLE_DATABASE_URL") and env.get("CONSOLE_MASTER_KEY"):
        console_store = ConsoleSecretStore(
            env["CONSOLE_DATABASE_URL"], env["CONSOLE_MASTER_KEY"],
            org=env.get("CONSOLE_ORG"))
        env, from_console = apply_console_secrets(env, console_store)
    cfg = load_config(env)
    if not cfg.agent_credential_env():
        log.warning(
            "no Anthropic credential at boot — role runs wait for Factory Console "
            "to send one on POST /events, or for CONSOLE_DATABASE_URL")
    ledger = Ledger(cfg.database_url)
    # Deployments on the placeholder App id cannot mint their own tokens; the
    # Console that dispatches their runs mints for them. Registration happens
    # per repo as dispatches arrive, so this is inert until one carries the
    # console_url and installation_id to use.
    app = GitHubApp(cfg, console=ConsoleTokenSource(cfg.dispatch_token.reveal()))
    if not app.can_mint():
        log.warning(
            "GITHUB_APP_PRIVATE_KEY is a placeholder — GitHub tokens can only come "
            "from the Console. Long roles will 401 unless /dispatch carries "
            "console_url and installation_id.")
    source = FactorySource(cfg, local_path=os.environ.get("FACTORY_LOCAL_PATH"))
    runner = RoleRunner(cfg, source)
    engine = Engine(cfg, ledger, app, runner, default_probe(cfg),
                    transcript_dir=os.environ.get("TRANSCRIPT_DIR"))
    graph = build_graph(engine, checkpointer=make_checkpointer(cfg.database_url))
    processor = Processor(engine, graph)
    return cfg, ledger, engine, create_app(cfg, ledger, processor), (console_store, from_console)


def sweep_targets(engine, ledger) -> list[str]:
    """The repos this pass sweeps: everything the ledger has seen, plus
    `CLAIMED_REPOS`.

    `CLAIMED_REPOS` used to be the whole list, and it is optional and empty in
    every shipped config — so the reconciler swept nothing, silently, in a
    default deployment. That is only a delay for the states a human is going
    to click anyway, but an expedited task at `factory:ready` has no click
    left in front of it (FACTORY.md §4a): a missed delivery there parks it for
    good, and the sweep is the only thing that would have found it.

    A repo the orchestrator has been handed a delivery for is a repo it
    drives, so the ledger already knows the answer. `CLAIMED_REPOS` stays
    honoured, and still earns its keep for a repo whose very first delivery is
    the one that went missing.
    """
    return sorted({*engine.cfg.claimed_repos, *ledger.known_repos()})


def start_reconciler(engine, ledger, console: tuple | None = None,
                     interval_seconds: int = 900) -> threading.Thread:
    def loop() -> None:
        warned_empty = False
        while True:
            if console and console[0] is not None:
                refresh_console_secrets(engine.cfg, console[0], console[1])
            # Re-read every pass: a repo whose first delivery arrives after
            # boot joins the sweep without a restart.
            repos = sweep_targets(engine, ledger)
            if not repos and not warned_empty:
                log.warning(
                    "reconciler has no repos to sweep yet — it starts sweeping each repo "
                    "as its first delivery arrives; set CLAIMED_REPOS to sweep before that")
                warned_empty = True
            for full in repos:
                owner, repo = full.split("/", 1)
                try:
                    sweep_repo(engine.port(owner, repo), ledger,
                               port_for=engine.port)
                except Exception:  # noqa: BLE001
                    log.exception("reconcile sweep failed for %s", full)
            time.sleep(interval_seconds)

    t = threading.Thread(target=loop, daemon=True, name="reconciler")
    t.start()
    return t


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    cfg, ledger, engine, app, console = build_service()
    start_reconciler(engine, ledger, console)
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
