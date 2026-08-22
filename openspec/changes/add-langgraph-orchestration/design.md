# Design: LangGraph orchestration layer

## Context

See `proposal.md — Why` for motivation. The load-bearing facts about the
current implementation:

- **All orchestration logic is inside one reusable workflow**,
  `.github/workflows/factory-pipeline.yml` (~1,600 lines): a `route` job
  (inline `github-script` JS implementing the whole decision table), an
  `agent` job (credential check → in-progress marker → checkout → factory
  clone at `factory_ref` into `RUNNER_TEMP` → no-op snapshot → model probe →
  `claude-code-action` / `claude -p` → no-op verify → failure report →
  marker cleanup), plus three chaining jobs (`architect-chain`,
  `release-chain`, `release-intake`) that exist only because labels applied
  with the workflow token emit no events (GitHub anti-recursion).
- **Consuming repos hold no logic** — a ~20-line caller stub owns triggers
  and the version pin; config lives in `.factory/profile.json` and
  `.github/factory-{models,approvers,release}.json`.
- **The Factory Console** (`software-factory-view`) is a lens over GitHub:
  it ingests GitHub App webhooks and projects issue/label/PR state. It
  reads nothing from Actions except run *links*. Anything that keeps GitHub
  authoritative keeps the Console working unmodified.
- **`scripts/test-router.js`** already tests the router by extracting the
  inline script from the workflow YAML and driving it with a stubbed
  `github` client — proof that the routing logic is separable from Actions,
  and the seed of the conformance suite.

Constraints that shape this design:

- The state machine (FACTORY.md §3), gates (§4), role prompts, OpenSpec
  conventions, and protected-branch enforcement (§8a) must not change.
- Existing consuming repos must be untouched unless they opt in.
- The two routers (JS in the workflow, Python in the orchestrator) must not
  drift.

## Goals / Non-Goals

**Goals:**

- A production-shaped LangGraph orchestrator that can drive one repo or an
  estate, deployable as a single container next to Postgres.
- One canonical statement of routing behaviour, mechanically enforced on
  both engines.
- Clean stand-down/claim protocol so migration is a one-file PR in the
  consuming repo, both directions.

**Non-Goals:**

- Replacing GitHub Actions. Actions remains the default engine and the
  zero-infrastructure path; the orchestrator is for estates that need what
  a long-lived service gives.
- Moving factory state into the orchestrator (no second source of truth;
  LangGraph checkpoints are execution bookkeeping only).
- New pipeline stages, roles, gates or label semantics.
- Console changes. (A later change may teach the Console to link to
  orchestrator run logs; the marker/label traces it renders already work.)
- Supporting non-GitHub forges (GitLab etc.). The engine contract is a
  prerequisite for that, but it is out of scope here.

## Decisions

### D1. The orchestrator is a separate service; GitHub stays the state machine

The LangGraph service replaces only the *motor* (Actions), never the *state*
(GitHub). Every node re-reads GitHub before acting; checkpoints exist for
resumability and observability, and are always subordinate to what labels
say. This is what makes migration trivial (no state to move), rollback safe,
and the Console compatible by construction.

*Alternative considered:* making LangGraph state authoritative with GitHub
as a projection. Rejected: it inverts the factory's founding rule, breaks
"any human may take over any stage by setting the next label", and makes the
Console wrong.

### D2. Python service under `orchestrator/` in this repo

`orchestrator/` is a Python 3.11+ package (LangGraph is Python-first;
`langgraph`, `langchain-anthropic`, `langgraph-checkpoint-postgres`,
FastAPI + uvicorn for the webhook endpoint). It lives in this repo so the
router, fixtures, role prompts and pipeline evolve in one PR and ship from
one tagged ref — the same reason the reusable workflow lives here.

*Alternative considered:* a separate repo. Rejected: router parity is the
main drift risk and same-repo CI is the cheapest enforcement.

*Alternative considered:* LangGraph JS to share the router source with the
workflow. Rejected: the Python ecosystem is where LangGraph is strongest,
and source sharing is impossible anyway — the Actions router must stay
inline `github-script` JS (a called workflow can't install dependencies
before routing without paying a job's cold start). Parity comes from
fixtures, not shared source (D3).

### D3. Parity by conformance fixtures, not shared code

The decision table is captured as JSON fixtures:
`orchestrator/conformance/fixtures/*.json`, each `{event, repoState,
expected: {role, issues, mutations, replies}}`. Two harnesses consume them:
`scripts/test-router.js` (extended from the existing extraction harness)
runs them against the workflow's inline router; `pytest` runs them against
the Python router. Both run in this repo's CI on every PR; a fixture change
without both harnesses green cannot merge. FACTORY.md's decision table
prose becomes documentation of the fixtures rather than the other way
round.

*Alternative considered:* generating both routers from one declarative
table. Rejected as over-engineering: the router's value is in its guarded
side-effects and explanatory replies, which don't compress into a table
without inventing a DSL nobody else can read.

### D4. Graph shape: event-driven invocations on per-issue durable threads

One `StateGraph`, invoked per routed event, with `thread_id =
"<owner>/<repo>#<issue>"` and a Postgres checkpointer.

```
webhook → verify+ledger → queue ─→ route (Python router)
                                      │ role=none → explanatory reply (if due) → END
                                      ▼
                            claim_check (engine-selection guard)
                                      ▼
                            mark_in_progress → snapshot → resolve_model
                                      ▼
                            run_role (isolated workspace, headless Claude Code)
                                      ▼
                            verify_no_op → clear_marker
                                      ▼
                    ┌── conditional edges (same conditions as today's chains) ──┐
                    │ planner ok → run architect (same thread)                  │
                    │ G0 approved → release fan-out: Send() one branch per      │
                    │   backlog issue (max-parallelism from config, no          │
                    │   fail-fast), receipt comment on the tracker              │
                    │ task closed → dispatch on the parent epic's thread        │
                    └────────────────────────────────────────────────────────────┘
```

Gate waits hold no compute: the graph ends after posting its hand-off, and
the *next* webhook (label flip / `Approved` comment) starts the next
invocation on the same thread. The thread accumulates the issue's execution
history for observability and gives crash-resume via the checkpointer.

*Alternative considered:* one long-lived graph run per epic, parked at
gates with `interrupt()`. Rejected for v1: it duplicates state GitHub
already holds (the parked position *is* the label), makes "human does a
stage by hand" a divergence to reconcile, and turns every gate into a
pending interrupt to administer. The event-driven shape mirrors the proven
Actions behaviour exactly; interrupts remain available later for
orchestrator-native approvals if ever wanted.

### D5. Role execution: headless Claude Code CLI in throwaway workspaces

`run_role` shells out to `claude -p` exactly as the pipeline's push path
already does — same prompt assembly (FACTORY.md + `commands/<role>.md` from
the pinned factory ref, cloned outside the workspace), same
`--allowedTools`, `--permission-mode acceptEdits`, `--max-turns`, wrapped in
a per-run timeout and a fresh clone under an isolated per-run directory
that is deleted afterwards. LangChain is used where an LLM call is a
*library* call (model-chain probe pings); the roles themselves stay Claude
Code sessions so plugin skills, hooks (`protect-branches.py`), and
`.claude/settings.json` deny rules keep working unchanged.

*Alternative considered:* reimplementing roles as LangChain agents with
GitHub tools. Rejected: it forks the role behaviour from the plugin/Actions
path, loses the Claude Code tool ecosystem and the §8a hook enforcement,
and violates "same bytes, same behaviour" parity.

### D6. Claim protocol: config file + engine-side guards on both engines

`.github/factory-orchestrator.json` (template in `templates/`), read from
the default branch:

```json
{ "engine": "langgraph", "endpoint": "https://factory.example.com", "runners": { "max_parallel": 4 } }
```

- The reusable workflow's `route` job loads it (same `loadJson` pattern as
  the release config) and exits `role=none` with a log line when `engine`
  is external. The caller stub is untouched — existing stubs get the
  stand-down by bumping `factory_ref`.
- The orchestrator's `claim_check` node fetches the file from the repo's
  default branch per event and drops events for repos that don't name it.
- Both checks evaluate at processing time, so a config race resolves to at
  most one engine acting per event (the spec's exactly-one guarantee).

*Alternative considered:* removing the caller stub when migrating.
Rejected as the primary mechanism: it makes rollback a multi-file change
and leaves no defence if a stub lingers. (Repos may still remove the stub
once stable; the guard makes it safe either way.)

### D7. GitHub identity: an orchestrator GitHub App

The orchestrator authenticates as its own GitHub App (webhook + installation
tokens scoped to claimed repos), the same model the Console uses. Agent runs
get an installation token as `GH_TOKEN`; `FACTORY_CROSS_REPO_TOKEN` remains
supported for estates that already use it. App-authored comments carry the
`<!-- factory-agent -->` marker, and the router's existing bot-comment
handling covers them.

### D8. Observability: run ledger + optional LangSmith

Every run writes a row (repo, issue, role, trigger, model + fallbacks,
timestamps, outcome, guard results, transcript path) to Postgres; a minimal
read-only HTTP surface lists runs and serves transcripts (this is what
failure comments link to, satisfying `engine-selection`'s "failure names its
engine"). `LANGSMITH_*` env vars enable tracing without code change.
Transcripts are stored with secrets redacted; the ledger never stores
credentials.

## Risks / Trade-offs

- **[Router drift between JS and Python]** → the fixture suite is a
  required check in this repo's CI for any PR touching either router or the
  fixtures; FACTORY.md documents fixtures as the canonical table.
- **[Double-driving during migration]** → both engines guard per event
  against the same config file (D6); the migration runbook flips config
  first, then verifies with a canary issue before filing real work.
- **[Long-lived credential surface (App key, Anthropic key on a server)]**
  → App scoped to claimed repos; tokens minted per run; G3 stays human-only
  and §8a hooks run inside every agent session; secrets only via env/secret
  store, never in the ledger or prompts.
- **[Operational burden the Actions path doesn't have (a service + DB to
  host)]** → accepted and explicit: the docs position Actions as the
  zero-infra default; compose file + health endpoint keep the minimum
  footprint one `docker compose up`.
- **[Concurrent runs on one host contending (disk, CPU, rate limits)]** →
  per-repo `max_parallel` (default 4, matching today's matrix cap) and a
  global runner-pool cap; workspaces are per-run and deleted.
- **[Webhook delivery gaps (missed events while down)]** → idempotency
  ledger + a reconciliation sweep on startup and on a timer: list issues
  whose state implies a pending automatic step (e.g. approved labels with
  no run recorded) and re-route them; GitHub redelivery covers the rest.

## Migration Plan

1. Ship the orchestrator and the stand-down check in one factory release
   (`factory_ref` bump). No consuming repo changes behaviour yet.
2. Pilot on one repo: deploy the service, install the App on the repo,
   merge `.github/factory-orchestrator.json` naming `langgraph`, verify
   stand-down (a caller-stub run logs the claim and does nothing), then run
   a canary issue end-to-end (intake → gates → task → PR).
3. Roll out per repo by merging the config file; leave the stubs in place.
4. **Rollback:** revert the config PR — Actions resumes on the next event.
   No state migration in either direction.

## Open Questions

- Whether the Console should render orchestrator run links natively (today
  it deep-links Actions runs only from comments, which already works) — a
  candidate follow-up change in `software-factory-view`.
- Whether the reconciliation sweep should also adopt orphaned
  `factory:in-progress` markers older than the run timeout, or leave them
  to the existing "remove by hand" guidance.
- SQLite checkpointer support for single-repo, no-Postgres installs —
  nice-to-have; can be answered during implementation without changing the
  specs.
