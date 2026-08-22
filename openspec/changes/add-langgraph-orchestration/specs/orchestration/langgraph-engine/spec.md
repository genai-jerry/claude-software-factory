# Delta: orchestration/langgraph-engine

## Purpose

Specifies the LangGraph-based orchestrator: a long-lived service that
consumes GitHub webhooks for the repos it has claimed and drives the factory
pipeline as a durable, checkpointed graph while satisfying the engine
contract in full.

## ADDED Requirements

### Requirement: The orchestrator conforms to the engine contract
The LangGraph orchestrator SHALL satisfy every requirement of
`orchestration/engine-contract` and `orchestration/engine-selection`,
including passing the shared routing conformance fixtures in its CI.

#### Scenario: Contract conformance gate
- **WHEN** the orchestrator's test suite runs
- **THEN** the shared routing fixtures execute against its router and a
  failure blocks the build

### Requirement: Webhook intake replaces Actions triggers
The orchestrator SHALL receive GitHub events for claimed repos as a GitHub
App webhook endpoint covering at least: issues (opened, labeled, closed,
milestoned, demilestoned), issue_comment (created), milestone (created,
opened), and push to the default branch on profile-relevant paths. It MUST
verify each delivery's HMAC signature, record it in an idempotency ledger,
acknowledge quickly, and process asynchronously; a delivery already
processed SHALL not be processed again. A manual dispatch entry point
(equivalent to Actions "Run workflow": any role against any issue number)
SHALL exist, restricted to operators.

#### Scenario: Bad signature rejected
- **WHEN** a webhook delivery fails signature verification
- **THEN** it is rejected and produces no routing

#### Scenario: Redelivered event is idempotent
- **WHEN** GitHub redelivers an event the orchestrator has already
  processed
- **THEN** no second role run starts for it

#### Scenario: Manual retry path
- **WHEN** an operator dispatches a role against an issue number by hand
- **THEN** the orchestrator runs that role under the same guards as an
  event-triggered run

### Requirement: The pipeline runs as a durable per-issue graph
The orchestrator SHALL execute each routed event as a graph invocation on a
durable thread keyed by the target issue, with state checkpointed to
persistent storage. Stage chaining that GitHub Actions performs in-run to
work around anti-recursion (planner→architect, gate-approval continuation,
release fan-out, re-dispatch) SHALL be expressed as graph edges and fan-out
within the orchestrator, producing the same GitHub traces. Waits on human
gates SHALL hold no compute: the graph parks at the gate and resumes when
the corresponding GitHub event arrives.

#### Scenario: Chained stages without event hacks
- **WHEN** the planner completes and the epic reaches `factory:planned`
- **THEN** the architect runs next within the same orchestrator flow, with
  the same verification (planner actually reached `factory:planned`) as the
  Actions chain

#### Scenario: Release fan-out with bounded parallelism
- **WHEN** gate G0 approves a milestone with N backlog issues
- **THEN** each issue's intake runs as its own parallel branch under a
  configured concurrency cap, one branch's failure never cancelling the
  others, and the tracker receives the same receipt comment

#### Scenario: Resume after restart
- **WHEN** the orchestrator process restarts while threads are parked at
  gates or runs are queued
- **THEN** parked threads resume on their next event from checkpointed +
  re-read GitHub state, and no queued run is lost or duplicated

### Requirement: Role runs execute in isolated workspaces
For each role run the orchestrator SHALL prepare a fresh, isolated workspace
containing a clone of the consuming repo, resolve the factory handbook and
role prompt from the pinned factory ref outside that workspace, and execute
headless Claude Code with the factory's allow-listed tools, permission mode,
turn budget, and per-run timeout. Concurrent runs SHALL not share
workspaces. GitHub operations from within a run use credentials scoped to
the claimed repos (plus the cross-repo token where the estate configures
one).

#### Scenario: Workspace isolation
- **WHEN** two role runs execute concurrently for different issues
- **THEN** each operates in its own workspace and neither can read or
  modify the other's working tree

#### Scenario: Factory files cannot leak into PRs
- **WHEN** a role stages all changes in its workspace
- **THEN** the factory's own handbook, prompts and orchestrator files are
  not in the workspace and cannot enter the PR

### Requirement: Model resolution uses the repo's preference chains
The orchestrator SHALL resolve each role's model from the consuming repo's
`.github/factory-models.json` preference chain, probing accessibility with
the run's credential, warning per fallback, defaulting missing roles to the
factory's documented default, and failing the run with a clear error when no
model in the chain is accessible.

#### Scenario: Chain fallback recorded
- **WHEN** the preferred model is inaccessible and the second is used
- **THEN** the run telemetry records the fallback and the run proceeds

### Requirement: Runs are observable outside GitHub
The orchestrator SHALL expose structured run telemetry — per run: repo,
issue, role, trigger event, model used and fallbacks, start/end, outcome,
guard results, and links to full agent transcripts — via a queryable
interface, and SHALL support optional tracing integration. Failure comments
posted on issues SHALL link to the corresponding run's log. Telemetry SHALL
never include credentials or raw secrets.

#### Scenario: From issue to run log
- **WHEN** a human follows the run-log link in a failure comment
- **THEN** they reach the specific run's telemetry including the agent
  transcript and the guard that failed

#### Scenario: Live runs are enumerable
- **WHEN** an operator asks the orchestrator what is running now
- **THEN** it lists in-flight runs by repo, issue and role, matching the
  `factory:in-progress` markers on GitHub
