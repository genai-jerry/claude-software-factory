# Delta Spec: expedite/staging-gate

## Purpose

Defines the new epic state `factory:epic-ready` and gate GS (staging
release): the explicit human approval that stands between a fully assembled
epic and the integration branch. Applies to every epic, expedited or not;
gate G3 (production) is unchanged.

## ADDED Requirements

### Requirement: The epic-ready state

A new state label `factory:epic-ready` SHALL mean: the epic's implementation
is complete and proven as far as it can be without touching staging —
with `epics: true`, every task is `factory:on-epic` and the epic branch's
full suite is green; with `epics: false`, every task is
`factory:ready-to-ship`. It SHALL be set on the epic by the factory: by the
Release run that lands the last task in its end state, or by the Dispatcher
when a task-close re-dispatch finds every task already there. It SHALL be
created by `scripts/setup-labels.sh`, sit between `factory:on-epic` and
`factory:in-staging` in the state table, and apply to expedited and
non-expedited epics alike.

#### Scenario: Last assembled task flips the epic

- **WHEN** a Release phase-1 run moves the final task of an epic to
  `factory:on-epic` and the epic branch suite is green
- **THEN** the epic flips to `factory:epic-ready` and no epic → integration
  merge happens in that run

#### Scenario: Set for non-expedited epics too

- **WHEN** a human manually started every stage of an epic and its last task
  reaches `factory:on-epic`
- **THEN** the epic still flips to `factory:epic-ready` — the informal
  "start Release phase 2 by hand" step no longer exists

### Requirement: Gate GS — human approval to release to staging

`factory:epic-ready` SHALL be a human gate. A `staging` key in
`.github/factory-approvers.json` names its approvers; when absent, the
`release` list applies; both absent falls back to any owner/member/
collaborator. On entering the state the factory SHALL assign and @-mention
the approvers with the evidence (epic assembly report, suite results) and
the exact control. The gate opens when an approver comments exactly
`Approved` on the epic (strict match, like every gate comment) or applies
the equivalent Console action. Auto-advance SHALL never open this gate,
whatever markers the epic carries.

#### Scenario: Approval starts the staging release

- **WHEN** a `staging` approver comments `Approved` on an epic at
  `factory:epic-ready`
- **THEN** the Release Manager runs phase 2: with `epics: true`, merge the
  integration branch into the epic branch, re-verify, open and merge the
  epic → integration PR; with `epics: false`, merge the epic's task PRs onto
  the integration branch in dependency order — then verify staging and move
  the epic to `factory:in-staging`

#### Scenario: Unauthorized approval is refused

- **WHEN** a user outside the configured `staging` list comments `Approved`
  on an epic at `factory:epic-ready`
- **THEN** the factory replies naming the required approvers and starts
  nothing

#### Scenario: Expedite does not reach past the gate

- **WHEN** an expedited epic sits at `factory:epic-ready`
- **THEN** nothing advances it until a human approves gate GS

### Requirement: Gate G3 is unchanged

Promotion from the integration branch to the default branch SHALL remain
exactly as specified today: `factory:in-staging`, promotion PR(s) merged by
a human through the GitHub UI, never comment-approvable, never performed by
an agent, protected by the existing enforcement layers. Nothing in expedite
mode or gate GS alters any G3 behavior, including the staging-failure
demotion path back to `factory:on-epic`.

#### Scenario: Comment approval still refused at G3

- **WHEN** anyone comments `Approved` on an epic at `factory:in-staging`
- **THEN** the factory replies that G3 is merge-click only, exactly as today

## MODIFIED Requirements

### Requirement: Release phase 2 starts from gate GS

(Modifies `branching/epic-promotion`.) The Release Manager SHALL begin the
epic → integration merge only from a gate-GS approval on an epic at
`factory:epic-ready`, rather than self-directing when it observes the epic
complete. The mechanics of the merge, staging verification, promotion PRs
and the demotion path are unchanged. A demoted epic (integration merge
reverted after a red staging diagnosis) returns to `factory:on-epic` and,
once repaired and reassembled, flips to `factory:epic-ready` again — gate GS
is re-approved for the retry.

#### Scenario: Demotion re-arms the gate

- **WHEN** an epic's integration merge is reverted off a red staging and its
  fix lands the epic back at all-tasks-`factory:on-epic`, green
- **THEN** the epic flips to `factory:epic-ready` and waits for a fresh GS
  approval before returning to staging
