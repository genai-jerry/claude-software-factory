# Delta: orchestration/engine-selection

## Purpose

Lets each consuming repo declare which orchestration engine drives it and
guarantees exactly one engine acts on a repo at a time, including a safe
migration path between GitHub Actions and an external engine in either
direction.

## ADDED Requirements

### Requirement: A repo declares its orchestration engine
A consuming repo SHALL declare its engine in
`.github/factory-orchestrator.json` with an `engine` key whose value is
`"github-actions"` or an external engine identifier (initially
`"langgraph"`). A missing or unparseable file SHALL mean `"github-actions"`,
preserving today's behaviour for every existing consuming repo with no
action on their part.

#### Scenario: Default is GitHub Actions
- **WHEN** a consuming repo has no `.github/factory-orchestrator.json`
- **THEN** the Actions caller stub and reusable pipeline drive the repo
  exactly as they do today

#### Scenario: External engine declared
- **WHEN** the file declares `"engine": "langgraph"` on the default branch
- **THEN** the external engine drives the repo and the Actions pipeline
  stands down

### Requirement: Exactly one engine drives a repo at a time
At most one engine SHALL execute factory roles for a repo at any moment.
When an external engine is declared, the reusable Actions pipeline SHALL
short-circuit: its route job reads the orchestrator config from the caller's
checkout and exits without routing (a visible log line, no role run, no
label mutation). An external engine SHALL likewise refuse to act on a repo
whose config does not name it.

#### Scenario: Actions stands down
- **WHEN** a GitHub event fires the caller stub in a repo declaring an
  external engine
- **THEN** the workflow run completes without starting any role, mutating
  any label, or posting any comment, and its log states which engine holds
  the claim

#### Scenario: External engine refuses an unclaimed repo
- **WHEN** an external engine receives a webhook for a repo whose
  orchestrator config does not name it
- **THEN** it acknowledges the delivery but takes no action on the repo

#### Scenario: No double execution during a config race
- **WHEN** the engine declaration changes while events are in flight
- **THEN** each event is acted on by at most one engine (both engines
  evaluate the claim against the config at the time they process the event,
  and at most one can match)

### Requirement: Migration between engines is safe and reversible
Switching a repo's engine SHALL be a reviewed change to
`.github/factory-orchestrator.json` on the default branch, and SHALL be
possible in both directions. Because all pipeline state lives on GitHub, a
switch MUST NOT require state migration: issues continue from their current
`factory:*` labels under the new engine. In-flight role runs started by the
previous engine run to completion under that engine's guards; the new engine
picks up from the next event.

#### Scenario: Mid-pipeline switch
- **WHEN** a repo switches engines while an epic sits at
  `factory:design-ready`
- **THEN** the gate approval that follows is routed by the new engine and
  the epic proceeds without any label or content migration

#### Scenario: Roll back to Actions
- **WHEN** an external engine misbehaves and the config is reverted to
  `"github-actions"`
- **THEN** the Actions pipeline resumes routing from the repo's current
  state on the next event, with no residue from the external engine beyond
  its ordinary GitHub traces

### Requirement: Engine identity is visible on the repo's traces
Traces an engine leaves on GitHub (failure reports, explanatory replies,
run-log links) SHALL identify which engine produced them and link to that
engine's run log for the run in question, so "where is this running and
where do I look when it fails" has one answer per repo.

#### Scenario: Failure names its engine
- **WHEN** a role run fails under an external engine
- **THEN** the failure comment on the issue links to that engine's run log
  rather than a GitHub Actions run
