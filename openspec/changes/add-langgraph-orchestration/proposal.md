# Proposal: Support LangChain/LangGraph as an additional orchestration layer

## Why

Today the factory's *execution* layer is welded to GitHub Actions: the router
(~660 lines of `github-script` inside `factory-pipeline.yml`), the agent jobs,
the planner→architect chain, the release fan-out and every guard live inside a
reusable workflow that only GitHub Actions can run. That coupling imposes real
limits — 45-minute job ceilings, in-run chaining hacks forced by GitHub's
anti-recursion rules (labels applied by the workflow token emit no events),
cold-start cost on every run (VM boot, `npm install`, model probes),
observability confined to the Actions tab, no way to run the factory against
repos whose owners cannot or will not use Actions (minutes budget, self-hosted
policy, air-gapped runners), and no local/debuggable execution path for
factory development itself.

The factory's own foundations make an alternative feasible: **GitHub is the
state machine and OpenSpec is the content** — GitHub Actions is only the motor
that reads events and turns them into agent runs. A second motor can drive the
same state machine, provided it drives it identically. LangGraph (durable
graph execution, checkpointing, human-in-the-loop interrupts, retries,
LangSmith tracing) plus LangChain (model abstraction) is a natural fit for
that motor: a long-lived service that consumes GitHub webhooks, routes them
with the same decision table, executes the same role prompts through headless
Claude Code, and leaves byte-identical traces on GitHub.

## What Changes

- **Extract an engine-neutral orchestration contract.** The routing decision
  table, guards (no-op guard, in-progress marker, approver enforcement,
  explanatory replies), trace conventions (`<!-- factory-agent -->`, label
  flips) and security invariants (G3 human-only merge, allowed-tools list,
  role prompt assembly) are specified independently of GitHub Actions, so any
  engine can be validated against them. A shared, engine-agnostic conformance
  fixture set (extending `scripts/test-router.js`) becomes the single source
  of routing truth.
- **Add per-repo orchestrator selection.** A consuming repo declares which
  engine drives it (`github-actions`, the default, or an external engine such
  as `langgraph`). Exactly one engine may drive a repo at a time; the Actions
  caller stub stands down cleanly when an external engine holds the claim.
- **Add a LangGraph orchestrator service** (`orchestrator/`, Python) that:
  - receives GitHub webhooks (GitHub App) for its claimed repos,
  - routes each event through a Python port of the router, verified by the
    shared conformance fixtures,
  - executes factory roles by launching headless Claude Code with the same
    handbook + role prompt + profile assembly and the same guardrails,
  - models the pipeline as a LangGraph `StateGraph` with a per-issue thread,
    Postgres/SQLite checkpointing, native fan-out (`Send`) for release
    batches, in-graph chaining (planner→architect) without anti-recursion
    workarounds, and gate waits expressed as interrupts resumed by webhook
    events,
  - resolves models through the same `.github/factory-models.json` preference
    chains via LangChain's Anthropic integration for probing,
  - emits structured run telemetry (optionally LangSmith) replacing the
    Actions-tab run log as the "where is it running" answer.
- **No change to the state machine or content model.** Labels, gates,
  approvers, OpenSpec folders, branch/PR conventions, comment markers and the
  Factory Console's ingestion all stay exactly as they are. The Console keeps
  working unmodified because GitHub remains the sole source of truth.

## Capabilities

### New Capabilities

- `orchestration/engine-contract`: What any orchestration engine must do to
  drive the factory — routing parity with the canonical decision table,
  mandatory guards and traces, role execution rules (prompt assembly, tool
  allow-list, turn/time budgets), security invariants, and the conformance
  fixtures that prove parity.
- `orchestration/engine-selection`: How a consuming repo declares its engine,
  how exactly-one-engine-at-a-time is enforced, how the Actions caller stub
  stands down, and how an estate migrates a repo between engines (both ways).
- `orchestration/langgraph-engine`: The LangGraph/LangChain orchestrator
  service — webhook intake and verification, graph topology, checkpointed
  per-issue threads, gate handling, role execution sandbox, model resolution,
  credentials, failure reporting, and observability.

### Modified Capabilities

<!-- none — openspec/specs/ is empty; the existing behaviour is documented in
     FACTORY.md and becomes the baseline these new specs encode -->

## Impact

- **New code:** `orchestrator/` Python package (LangGraph, LangChain,
  webhook receiver, role runner); JSON conformance fixtures shared with
  `scripts/test-router.js`.
- **Changed code:** the Actions caller stub template and reusable pipeline
  gain an engine-selection short-circuit; `templates/` gains an orchestrator
  config template; FACTORY.md gains an orchestration-layer section (§2a
  becomes one engine of two).
- **Unchanged:** role prompts (`commands/*.md`), FACTORY.md state machine
  (§3), gates (§4), OpenSpec conventions (§5), branching (§6),
  protected-branch enforcement (§8a), the `factory` plugin, and the Factory
  Console (`software-factory-view`) — it ingests GitHub webhooks and GitHub
  stays authoritative.
- **Dependencies:** Python 3.11+, `langgraph`, `langchain-anthropic`,
  `langgraph-checkpoint-postgres` (or SQLite for single-repo installs), a
  GitHub App registration for the orchestrator, and host infrastructure for
  a long-lived service (container; compose file provided).
- **Risks:** router drift between the two implementations (mitigated by the
  shared fixture suite as a required CI check), double-driving a repo during
  migration (mitigated by the claim protocol in `engine-selection`), and a
  long-lived service's credential surface (mitigated by scoping the GitHub
  App to claimed repos and keeping G3 human-only).
