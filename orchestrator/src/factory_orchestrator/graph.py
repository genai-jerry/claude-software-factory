"""The pipeline as a LangGraph StateGraph.

One graph invocation per routed GitHub event, on a durable thread keyed by
the target issue (``owner/repo#issue``). The node chain mirrors the Actions
agent job step for step; what Actions does with in-run YAML workarounds
(planner→architect chaining, the gate-G0 release fan-out, re-dispatch)
becomes ordinary graph structure: a ``chain`` join node computes follow-up
work and conditional edges ``Send`` it back through ``run_role`` until
nothing is pending. At a human gate the invocation simply ends — the parked
position is the label on GitHub, and the next webhook resumes the thread.

    route ──► [Send run_role ×N] ──► chain ──► [Send …] ──► chain ──► END
      │                                ▲
      └── role=none, release approved ─┘   (fan-out from gate G0)

Checkpointing (SQLite or Postgres by DATABASE_URL) makes threads
restart-safe and inspectable; state is execution bookkeeping only — every
node re-reads GitHub before acting (engine-contract).
"""

from __future__ import annotations

import json
import logging
import operator
import tempfile
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import claim
from .config import Config
from .github_app import GitHubApp, RepoPort, parse_json_or_empty
from .guards import (
    clear_in_progress,
    mark_in_progress,
    no_op_reason,
    report_failure,
    report_start,
    snapshot,
    verify_no_op,
)
from .ledger import Ledger
from .models import ModelResolutionError, Probe, load_models_config, resolve_model
from .role_runner import RoleRunner
from .router import RepoConfig, Router, release_chain

log = logging.getLogger("factory-orchestrator.graph")

MAX_ROUNDS = 4  # initial + architect chain + release fan-out + slack; a backstop, not a schedule


class PipelineState(TypedDict, total=False):
    event_name: str
    payload: dict[str, Any]
    owner: str
    repo: str
    trigger: str
    pending: list[dict[str, Any]]                 # [{"role": ..., "issue": ...}]
    completed: Annotated[list[dict[str, Any]], operator.add]
    release_issue: str
    release_dispatched: bool
    round: int


class RunItem(TypedDict):
    owner: str
    repo: str
    role: str
    issue: int
    trigger: str


class Engine:
    """Dependency bundle the graph nodes close over."""

    def __init__(self, cfg: Config, ledger: Ledger, app: GitHubApp,
                 runner: RoleRunner, probe: Probe,
                 transcript_dir: str | None = None,
                 port_factory=None):
        self.cfg = cfg
        self.ledger = ledger
        self.app = app
        self.runner = runner
        self.probe = probe
        self.transcript_dir = Path(transcript_dir or tempfile.mkdtemp(prefix="transcripts-"))
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self._port_factory = port_factory or (lambda o, r: app.repo_client(o, r))

    def port(self, owner: str, repo: str) -> RepoPort:
        return self._port_factory(owner, repo)

    def repo_config(self, port: RepoPort) -> RepoConfig:
        return RepoConfig(
            release=parse_json_or_empty(port.get_file(".github/factory-release.json")),
            approvers=parse_json_or_empty(port.get_file(".github/factory-approvers.json")),
        )

    def max_parallel(self, port: RepoPort) -> int:
        runners = claim.orchestrator_settings(port).get("runners")
        if isinstance(runners, dict) and isinstance(runners.get("max_parallel"), int):
            return max(1, runners["max_parallel"])
        return self.cfg.max_parallel_default


# ----------------------------------------------------------------- nodes
def build_graph(engine: Engine, checkpointer=None):
    def route_node(state: PipelineState) -> dict[str, Any]:
        port = engine.port(state["owner"], state["repo"])
        result = Router(port, engine.repo_config(port)).route(
            state["event_name"], state["payload"])
        pending = [{"role": result.role, "issue": int(n)} for n in result.issues] \
            if result.role != "none" else []
        log.info(
            "route event=%s repo=%s/%s role=%s issues=%s release=%s",
            state["event_name"], state["owner"], state["repo"],
            result.role, [p["issue"] for p in pending], result.release_issue or "-",
        )
        return {"pending": pending, "release_issue": result.release_issue,
                "release_dispatched": False, "round": 0, "completed": []}

    def run_role_node(item: RunItem) -> dict[str, Any]:
        summary = execute_role(engine, item)
        return {"completed": [summary]}

    def chain_node(state: PipelineState) -> dict[str, Any]:
        port = engine.port(state["owner"], state["repo"])
        pending: list[dict[str, Any]] = []
        this_round = [c for c in state.get("completed", []) if c.get("round") == state["round"]]

        # planner → architect, gated on the planner actually reaching
        # factory:planned (mirrors the architect-chain job's check).
        for c in this_round:
            if c["role"] == "planner" and c["status"] == "success":
                epic = port.get_issue(c["issue"]) or {}
                labels = [(l if isinstance(l, str) else l.get("name"))
                          for l in epic.get("labels", [])]
                if "factory:planned" in labels:
                    pending.append({"role": "architect", "issue": c["issue"]})
                else:
                    log.info("Planner did not reach factory:planned - not chaining architect.")

        # Gate G0's mechanical half: release the milestone once, then fan the
        # freed issues out as intake runs. Mirrors release-chain +
        # release-intake, including "one failure must not cancel the rest"
        # (each Send is independent).
        failed = any(c["status"] not in ("success", "no_op") for c in this_round)
        if (state.get("release_issue") and not state.get("release_dispatched")
                and not failed):
            released, _count = release_chain(port, int(state["release_issue"]))
            pending.extend({"role": "intake", "issue": int(n)} for n in released)
            return {"pending": pending, "round": state["round"] + 1, "release_dispatched": True}

        return {"pending": pending, "round": state["round"] + 1}

    def fan(state: PipelineState):
        if state["round"] >= MAX_ROUNDS:
            log.warning("round cap reached - ending invocation")
            return END
        items = state.get("pending") or []
        if items:
            return [Send("run_role", RunItem(
                owner=state["owner"], repo=state["repo"], role=i["role"],
                issue=i["issue"], trigger=state.get("trigger", state["event_name"]),
            ) | {"round": state["round"]}) for i in items]
        if state.get("release_issue") and not state.get("release_dispatched"):
            return "chain"
        return END

    builder = StateGraph(PipelineState)
    builder.add_node("route", route_node)
    builder.add_node("run_role", run_role_node)
    builder.add_node("chain", chain_node)
    builder.add_edge(START, "route")
    builder.add_conditional_edges("route", fan, ["run_role", "chain", END])
    builder.add_edge("run_role", "chain")
    builder.add_conditional_edges("chain", fan, ["run_role", "chain", END])
    return builder.compile(checkpointer=checkpointer)


def execute_role(engine: Engine, item: RunItem) -> dict[str, Any]:
    """One guarded role run — the whole Actions agent job as a function."""
    owner, repo, role, issue = item["owner"], item["repo"], item["role"], item["issue"]
    port = engine.port(owner, repo)
    run_id = engine.ledger.start_run(repo=f"{owner}/{repo}", issue=issue, role=role,
                                     trigger=item.get("trigger", ""))
    run_url = f"{engine.cfg.public_base_url}/runs/{run_id}"
    summary: dict[str, Any] = {"role": role, "issue": issue, "run_id": run_id,
                               "round": item.get("round", 0)}
    log.info("role start role=%s repo=%s/%s#%s run=%s log=%s",
             role, owner, repo, issue, run_id, run_url)
    mark_in_progress(port, issue)
    transcript_path = engine.transcript_dir / f"{run_id}.log"

    def note(phase: str, **extra: Any) -> None:
        payload = {"phase": phase, **extra}
        engine.ledger.update_run(run_id, outcome="running",
                                 guards=json.dumps(payload),
                                 transcript_path=str(transcript_path))

    try:
        try:
            transcript_path.write_text("")
            if not engine.cfg.agent_credential_env():
                raise ModelResolutionError(
                    "No Anthropic credential is available. Store ANTHROPIC_API_KEY or "
                    "CLAUDE_CODE_OAUTH_TOKEN in the Factory Console so it is forwarded "
                    "on POST /events, or set one on the orchestrator.")
            note("resolving model")
            resolved = resolve_model(role, load_models_config(port), engine.probe)
        except ModelResolutionError as e:
            engine.ledger.finish_run(run_id, outcome="error", error=str(e))
            report_failure(port, issue, role, run_url, reason=str(e))
            summary["status"] = "error"
            log.info("role finish role=%s repo=%s/%s#%s run=%s status=error reason=model",
                     role, owner, repo, issue, run_id)
            return summary
        extra = {"model": resolved.model, "fallbacks": resolved.fallbacks}
        engine.ledger.update_run(run_id, model=resolved.model,
                                 model_fallbacks=json.dumps(resolved.fallbacks))
        note("starting", **extra)
        # Start note before the no-op snapshot so it is not counted as the
        # role's own trace. Anyone watching the issue (or the Console card)
        # can follow the log without an Actions run.
        report_start(port, issue, role, run_url)
        before = snapshot(port, issue)
        outcome = engine.runner.run(
            owner=owner, repo=repo, role=role, issue=issue, model=resolved.model,
            github_token=engine.app.installation_token(owner, repo),
            on_phase=lambda phase: note(phase, **extra))
        traced = verify_no_op(port, issue, before, role)
        error: str | None = None
        if outcome.status == "success" and traced:
            status = "success"
        elif outcome.status == "success":
            status = "no_op"  # exit 0 but nothing visible happened: fail it
            error = no_op_reason(role, issue)
        elif outcome.status == "timeout":
            status = "timeout"
            error = f"Role '{role}' exceeded the {engine.cfg.role_timeout_seconds}s wall clock."
        else:
            status = outcome.status
            error = outcome.error or (
                f"Claude exited {outcome.exit_code}."
                if outcome.exit_code is not None else f"Role '{role}' failed.")
        body = outcome.transcript or ""
        if error:
            body = f"{error}\n\n--- agent transcript ---\n\n{body}".strip()
        transcript_path.write_text(body)
        guards = {"before": before.__dict__, "trace": traced, "phase": "finished",
                  "model": resolved.model, "fallbacks": resolved.fallbacks}
        engine.ledger.finish_run(run_id, outcome=status, model=resolved.model,
                                 model_fallbacks=resolved.fallbacks, guards=guards,
                                 transcript_path=str(transcript_path), error=error)
        if status != "success":
            report_failure(port, issue, role, run_url, reason=error)
        summary["status"] = status
        log.info("role finish role=%s repo=%s/%s#%s run=%s status=%s traced=%s",
                 role, owner, repo, issue, run_id, status, traced)
        return summary
    except Exception as e:  # noqa: BLE001 - a crashed run must still report + unmark
        log.exception("role crashed role=%s repo=%s/%s#%s run=%s",
                      role, owner, repo, issue, run_id)
        crash = f"{type(e).__name__}: {e}"
        engine.ledger.finish_run(run_id, outcome="error", error=crash)
        report_failure(port, issue, role, run_url, reason=crash)
        summary["status"] = "error"
        return summary
    finally:
        clear_in_progress(port, issue)


# ----------------------------------------------------------------- wiring
def thread_id_for(event_name: str, payload: dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name", "unknown/unknown")
    issue = (payload.get("issue") or {}).get("number")
    if issue is None:
        issue = (payload.get("inputs") or {}).get("issue_number", "repo")
    return f"{repo}#{issue}"


def make_checkpointer(database_url: str):
    """SQLite or Postgres checkpointing from the same DATABASE_URL as the ledger."""
    if database_url.startswith("sqlite"):
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
        path = database_url.split("///", 1)[-1] or ":memory:"
        return SqliteSaver(sqlite3.connect(f"{path}.graph" if path != ":memory:" else path,
                                           check_same_thread=False))
    if database_url.startswith("postgres"):
        from langgraph.checkpoint.postgres import PostgresSaver
        url = database_url.replace("postgresql+psycopg://", "postgresql://")
        saver = PostgresSaver.from_conn_string(url)
        saver.setup()
        return saver
    return None


class Processor:
    """webhook delivery -> claim check -> graph invocation on the issue's thread."""

    def __init__(self, engine: Engine, graph):
        self.engine = engine
        self.graph = graph

    def __call__(self, event_name: str, payload: dict[str, Any]) -> None:
        repository = payload.get("repository") or {}
        full = repository.get("full_name") or ""
        if "/" not in full:
            log.info("event without a repository - ignoring")
            return
        owner, repo = full.split("/", 1)
        token = (payload.get("inputs") or {}).get("github_token")
        if token and hasattr(self.engine.app, "cache_token"):
            self.engine.app.cache_token(owner, repo, token)
        port = self.engine.port(owner, repo)
        if not claim.claim_check(port, self.engine.cfg.engine_name):
            return
        issue_n = (payload.get("issue") or {}).get("number")
        if issue_n is None:
            issue_n = (payload.get("inputs") or {}).get("issue_number")
        thread = thread_id_for(event_name, payload)
        log.info("invoke graph event=%s action=%s repo=%s/%s issue=%s thread=%s",
                 event_name, payload.get("action", ""), owner, repo, issue_n or "-", thread)
        state: PipelineState = {
            "event_name": "workflow_dispatch" if event_name == "workflow_dispatch" else event_name,
            "payload": payload, "owner": owner, "repo": repo,
            "trigger": f"{event_name}:{payload.get('action', '')}",
        }
        config = {"configurable": {"thread_id": thread}}
        self.graph.invoke(state, config=config)
