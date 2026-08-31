# Delta Spec: expedite/auto-chaining

## Purpose

Defines the auto-advance map an expedited issue follows, its guards and
termination, and how each orchestration engine executes it. The marker's
semantics are in `expedite/expedite-marker`; the terminal gate is in
`expedite/staging-gate`.

## ADDED Requirements

### Requirement: The auto-advance map

While an issue is expedited (per `expedite/expedite-marker`) and not
`factory:blocked`, the factory SHALL advance it as follows, both when a state
is *reached* by a role completing and when the marker is *applied* to an issue
already sitting in that state:

- epic `factory:spec-ready` → auto-approve gate G1: merge the spec PR (same
  retarget/squash-merge routine as comment approval), flip to
  `factory:spec-approved`, run the Planner (the existing Planner→Architect
  chain applies unchanged)
- epic `factory:design-ready` → auto-approve gate G2: merge the design PR(s),
  flip to `factory:design-approved`, run the Dispatcher
- task `factory:ready` → start the Implementer without an `Approved` comment
- task `factory:in-review` → run the Reviewer
- task `factory:in-test` → run QA
- task `factory:ready-to-ship` → with `epics: true`, run Release phase 1
  (merge onto the epic branch → `factory:on-epic`); with `epics: false`, no
  auto action (see the staging-safety requirement)

Gate auto-approvals SHALL use the same merge-and-flip implementation as
comment approvals, refactored into a shared routine in each engine, so the
two paths cannot diverge. States the map does not name (including
`factory:intake`, `factory:backlog`, `factory:epic-ready`,
`factory:in-staging`, `factory:deployed`) SHALL never auto-advance.

#### Scenario: Applied at design-ready, chain runs to implementation

- **WHEN** `factory:expedite` is applied to an epic at `factory:design-ready`
- **THEN** the design PR(s) merge, the epic flips to
  `factory:design-approved`, the Dispatcher runs, and every task it marks
  `factory:ready` has its Implementer started automatically

#### Scenario: Rework rounds stay capped

- **WHEN** the Reviewer returns an expedited task to `factory:ready` for the
  third time
- **THEN** the existing rework cap applies: the task goes `factory:blocked`
  and no implementer is auto-started

#### Scenario: Re-dispatch feeds the chain

- **WHEN** an expedited epic's task closes and the Dispatcher's re-run marks a
  previously blocked task `factory:ready`
- **THEN** that task's Implementer starts automatically

### Requirement: Guards — blocked, in-progress, and termination

Auto-advance SHALL be suppressed while the issue (or, for gate flips, the
epic) carries `factory:blocked`; the existing blocked-resume flow re-runs the
halted stage, and expedite resumes with it when the marker is still present.
Every auto-start SHALL honor the `factory:in-progress` double-start guard
exactly as human-triggered starts do. The chain SHALL terminate at
`factory:epic-ready` (per `expedite/staging-gate`), on marker removal, and on
`factory:blocked` — there is no other exit and no cycle except the capped
reviewer rework loop.

#### Scenario: Blocked pauses, reply resumes

- **WHEN** QA marks an expedited task `factory:blocked` and a human later
  replies on the thread
- **THEN** nothing auto-advanced while blocked; the reply clears the label and
  re-runs QA, and the chain continues from QA's outcome

### Requirement: The chain never deploys staging

No auto-advanced action SHALL merge anything to the integration branch or the
default branch. With `epics: false`, the Release role — whose first merge
under that policy lands on the integration branch and deploys staging — SHALL
NOT be auto-run; expedited tasks accumulate at `factory:ready-to-ship` and the
epic flips to `factory:epic-ready` when all tasks are there. With
`epics: true`, auto-run Release phase 1 stops after epic-branch assembly
(`factory:on-epic`); the epic → integration merge waits on gate GS.

#### Scenario: epics false stops before the Release role

- **WHEN** an expedited task reaches `factory:ready-to-ship` in a repo with
  `epics: false`
- **THEN** no Release run starts automatically, and when every task of the
  epic is `factory:ready-to-ship` the epic flips to `factory:epic-ready`

### Requirement: Engine mechanics and parity

Both engines SHALL implement the map from this one decision table, pinned by
new conformance fixtures covering every scenario in this change; the fixtures
and both routers move in one PR. The LangGraph orchestrator SHALL execute
follow-ups in its `chain` node (fan-out via `Send`, per-role models as today,
round budget derived from the epic's task count instead of the fixed
constant). The Actions engine SHALL execute follow-ups by re-dispatching the
pipeline workflow (`workflow_dispatch`: role + issue, one dispatch per
follow-up issue) using `FACTORY_CROSS_REPO_TOKEN`, and SHALL only dispatch
follow-ups for issues whose state the current run changed. The existing
`architect-chain` behavior is absorbed by this mechanism and MUST remain
functionally identical for non-expedited epics.

#### Scenario: One run, one hop, next run continues

- **WHEN** the Actions engine finishes an expedited Implementer run that
  flipped a task to `factory:in-review`
- **THEN** that run dispatches exactly one pipeline run (role `reviewer`,
  that task), and the reviewer run in turn computes its own follow-up

### Requirement: Graceful degradation without the cross-repo token

On the Actions engine, when `FACTORY_CROSS_REPO_TOKEN` is not configured, the
chain step SHALL post a say-once comment on the issue explaining that
expedite auto-chaining needs the token on this engine and naming the manual
control for the current state, then stop cleanly. The normal next-step notice
still applies; nothing fails red and nothing stalls silently. The
orchestrator engine SHALL NOT require any extra credential.

#### Scenario: Missing PAT degrades visibly

- **WHEN** an expedited task reaches `factory:in-review` on the Actions engine
  and no `FACTORY_CROSS_REPO_TOKEN` secret exists
- **THEN** the run comments once that auto-chaining requires the token and how
  to start the Reviewer manually, and ends green

### Requirement: Every hop keeps the trace contract

Each auto-advanced transition SHALL keep the existing visible-trace rules:
the in-progress marker around agent runs, agent comments ending with the
agent marker, and the next-step notice rendered from
`handbook/next-step.json` — which SHALL gain expedited wording variants so an
expedited state's notice says the factory advances it automatically, and
SHALL keep today's wording when the marker is absent.

#### Scenario: Expedited wording on an auto-advancing state

- **WHEN** an expedited task lands at `factory:in-test`
- **THEN** the next-step notice says QA starts automatically and asks the
  reader for nothing, rather than pointing at the manual start controls
