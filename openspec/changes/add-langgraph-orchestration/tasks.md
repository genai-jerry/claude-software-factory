# Tasks: add-langgraph-orchestration

## 1. Conformance fixtures (single source of routing truth)

- [x] 1.1 Define the fixture schema (`orchestrator/conformance/SCHEMA.md` +
      JSON Schema): `{event, repoState: {labels, comments, milestones,
      configs}, expected: {role, issues, mutations, replies}}`; verify the
      schema validates a hand-written example fixture.
- [x] 1.2 Extend `scripts/test-router.js` to load and run JSON fixtures from
      `orchestrator/conformance/fixtures/` against the workflow's inline
      router (keeping its existing extraction harness); verify it fails on a
      deliberately wrong fixture and passes on the example.
- [x] 1.3 Write fixtures covering the full decision table: issue opened
      (human/bot/task/tracker/fast-track/profile), release gating parking
      and exemptions, milestone created, milestoned/demilestoned, `Plan
      release`, `Approved` in every state (authorized and not), blocked
      resume, task closed re-dispatch, labeled events (gates, hand-off
      notifications, in-progress no-route, fast-track hijack refusal),
      profile push trigger, and workflow_dispatch; verify
      `node scripts/test-router.js` passes every fixture against the
      existing workflow router (fixing fixtures, not the router, on
      mismatch).
- [x] 1.4 Add a CI workflow in this repo that runs the JS fixture harness on
      every PR touching the pipeline, fixtures, or (later) the Python
      router; verify it runs and gates on a test PR.

## 2. Engine selection (stand-down / claim)

- [x] 2.1 Add `templates/factory-orchestrator.json` and document the
      `engine` key (default `github-actions`); verify the template parses
      and matches the schema documented in FACTORY.md.
- [x] 2.2 Add the stand-down check to the reusable workflow's `route` job:
      load `.github/factory-orchestrator.json` from the caller checkout,
      and when `engine` is external set `role=none` and log which engine
      holds the claim; verify with fixtures (external engine → no route for
      every event; missing/invalid file → routing unchanged).
- [x] 2.3 Update FACTORY.md (§2a and a new orchestration-layer section) and
      wiki/Control-Architecture.md to describe engine selection, the claim
      protocol, and migration/rollback; verify the docs name the config
      file, both engines, and the one-file rollback.

## 3. Orchestrator service skeleton

- [x] 3.1 Scaffold `orchestrator/` (Python 3.11+, `pyproject.toml` with
      langgraph, langchain-anthropic, langgraph-checkpoint-postgres,
      FastAPI, uvicorn, httpx; ruff + pytest config); verify `pip install
      -e .[dev]` and `pytest` (empty suite) succeed.
- [x] 3.2 Implement config/env loading (App credentials, Anthropic
      credentials, database URL, factory repo + ref, runner caps) with
      validation and a redacting `__repr__`; verify unit tests cover
      missing/invalid config and that secrets never appear in logs.
- [x] 3.3 Implement the GitHub App client: webhook HMAC verification,
      installation-token minting scoped per repo, REST helpers used by the
      router (issues, labels, comments, milestones, PR merge for G1/G2
      document PRs); verify against recorded/mocked API tests.
- [x] 3.4 Implement the webhook endpoint + idempotency ledger + async queue
      (FastAPI → Postgres ledger → worker): verify signature rejection,
      duplicate-delivery no-op, and fast acknowledgement in integration
      tests.

## 4. Python router with conformance parity

- [x] 4.1 Port the routing decision table to `orchestrator/router.py`
      (pure function of event + repo state → route decision + side-effect
      plan, mirroring the JS router's guards, tracker/profile issue
      management, approver enforcement and explanatory replies); verify
      unit tests on the side-effect plan structure.
- [x] 4.2 Build the pytest conformance harness running every fixture from
      `orchestrator/conformance/fixtures/` against the Python router;
      verify all fixtures pass and the harness is wired into the repo CI
      gate from task 1.4.
- [x] 4.3 Implement the `claim_check` guard (fetch
      `.github/factory-orchestrator.json` from the default branch per
      event; act only when it names this engine); verify tests for named,
      unnamed, missing and unparseable config.

## 5. Graph and role execution

- [x] 5.1 Define the `StateGraph` with per-issue `thread_id` and the
      Postgres checkpointer: route → claim_check → mark_in_progress →
      snapshot → resolve_model → run_role → verify_no_op → clear_marker;
      verify a stubbed-role end-to-end test moves a fake issue and
      checkpoints the thread.
- [x] 5.2 Implement guard nodes to the engine contract: in-progress marker
      applied/removed in all outcomes (including timeout), no-op guard
      (comment count + `factory:*` snapshot compare), failure-report
      comment linking the run log, `<!-- factory-agent -->` marker on every
      posted comment; verify each guard with dedicated tests (e.g. silent
      role → run failed).
- [x] 5.3 Implement model resolution from `.github/factory-models.json`
      with accessibility probing via langchain-anthropic, per-fallback
      warnings, default chain for missing roles, and hard failure on an
      exhausted chain; verify tests cover fallback and exhaustion.
- [x] 5.4 Implement the role runner: per-run isolated workspace (fresh
      clone, deleted after), factory handbook + role prompt resolved from
      the pinned ref outside the workspace, `claude -p` with the factory
      allow-list/permission mode/turn budget, wall-clock timeout,
      installation token as `GH_TOKEN` (cross-repo token honoured);
      verify with a fake `claude` binary that prompt assembly matches the
      Actions path byte-for-byte and that workspaces are isolated and
      cleaned up.
- [x] 5.5 Implement chaining edges: planner→architect (with the
      reached-`factory:planned` check), G0 release fan-out via `Send` with
      per-repo `max_parallel` and no fail-fast plus the tracker receipt
      comment, task-closed re-dispatch on the parent epic; verify
      integration tests reproduce the Actions chains' traces.
- [x] 5.6 Implement the operator dispatch entry point (any role, any issue,
      authenticated) and the reconciliation sweep (startup + timer:
      re-route issues whose state implies a pending automatic step);
      verify tests for dispatch auth and for sweep picking up a missed
      approval event.

## 6. Observability and packaging

- [x] 6.1 Implement the run ledger (repo, issue, role, trigger, model +
      fallbacks, timestamps, outcome, guard results, transcript path) and
      the read-only HTTP surface for runs and transcripts (this is the
      failure-comment link target); verify ledger rows and endpoints in
      integration tests, and that transcripts are secret-redacted.
- [x] 6.2 Wire optional LangSmith tracing behind `LANGSMITH_*` env vars;
      verify the service boots identically with and without them.
- [ ] 6.3 Add Dockerfile + docker-compose (orchestrator + Postgres) and a
      health endpoint; verify `docker compose up` yields a healthy service
      that accepts a signed test webhook.
- [x] 6.4 Write `orchestrator/README.md`: deployment, App registration,
      claiming a repo, the migration runbook (config PR → stand-down check
      → canary issue → rollout) and rollback; verify the runbook's steps
      against the compose stack.

## 7. End-to-end validation

- [ ] 7.1 Full-pipeline rehearsal against a scratch repo: file an issue,
      drive intake → G1 → planner/architect → G2 → dispatch → implementer
      task PR under the orchestrator, confirming byte-identical trace
      conventions (labels, markers, receipts) and Console ingestion
      unaffected; record the transcript links in the change folder.
- [ ] 7.2 Migration + rollback rehearsal on the scratch repo: claim via
      config PR (verify Actions stands down with the log line), then revert
      (verify Actions resumes on the next event); document both runs.
- [x] 7.3 Run `openspec validate add-langgraph-orchestration --strict` and
      the full repo CI (JS + Python conformance suites); verify green.

## 8. Local development and VPS deployment (follow-up)

- [x] 8.1 Laptop harness: Makefile (install/test/lint/conformance/dev/
      smoke/compose targets), `scripts/dev.sh` (sqlite + uvicorn reload +
      dev-credential fallbacks), `scripts/smoke.py` (signed webhook, dedupe
      and bad-signature checks against a running instance), `.env.example`,
      and a "Test locally on your laptop" README section including the
      smee.io webhook bridge; verified by running dev.sh + smoke.py end to
      end (all checks pass).
- [x] 8.2 Support `GITHUB_APP_PRIVATE_KEY_B64` in config (docker env files
      cannot carry multi-line PEMs) and forward it through docker-compose;
      verified by unit tests (decode, precedence, invalid base64 rejected).
- [x] 8.3 `.github/workflows/deploy-orchestrator.yml` mirroring
      lighthouse-backend's deploy.yml (build → save/gzip → SCP → SSH load,
      env file from environment-scoped secrets, shared docker network,
      /data volume for sqlite + transcripts, docker-exec health check,
      prune; push-to-main on orchestrator/** + workflow_dispatch with an
      environment choice), plus the README runbook naming every secret and
      variable; verified by YAML parse and secret-name rules (no GITHUB_-
      prefixed secret names). Live deploy verification happens on the
      first push to main with the environment configured.

- [x] 8.4 Local deploy the lighthouse-backend way: `orchestrator/deploy.sh
      [environment] [action]` (up/down/restart/logs/status/build/rebuild +
      health/smoke) loading committed `config.<env>.env` files
      (local/staging/production placeholders, .env fallback seeded from
      .env.example), with lighthouse's usage/help and access-URL footer;
      verified by bash -n, the unknown-action exit path, and live
      `deploy.sh local health` + `deploy.sh local smoke` against a running
      dev server (all checks green). Compose actions need a Docker daemon
      (not available here), same caveat as 6.3.

## 9. Console-retained agent secrets (follow-up)

- [x] 9.1 software-factory-view: retain agent secrets on write — new
      `orchestrator_secrets` table (+ migration 0010), org-level settings
      route and per-repo onboarding step seal the value with
      CONSOLE_MASTER_KEY before the GitHub write-through, upsert per
      org+name, write-only API (GET exposes name + updatedAt only),
      retention skipped and reported when no master key is set; verified by
      5 new API tests (encrypt/decrypt round trip, upsert, metadata-only
      surface, allow-list, no-key fallback) with the full 121-test suite
      green.
- [x] 9.2 orchestrator: `console_secrets.py` — envelope decryption
      byte-compatible with the Console's crypto.ts (pinned by a vector
      generated with the real Node implementation), ConsoleSecretStore
      (TTL-cached reads, single-org auto-select, CONSOLE_ORG for
      multi-org), env-wins merge into config at startup, and rotation
      refresh on the reconciler timer that never breaks on a store outage;
      verified by 15 unit tests.
- [x] 9.3 Plumbing + docs: CONSOLE_DATABASE_URL / CONSOLE_MASTER_KEY /
      CONSOLE_ORG through .env.example, docker-compose and the deploy
      workflow (Anthropic deploy-secret requirement relaxed when the
      Console store is wired), README section, spec requirement
      (langgraph-engine: credential sourcing scenarios) and design
      decision D8a; verified by YAML parse, full orchestrator suite and
      `openspec validate --strict`.
