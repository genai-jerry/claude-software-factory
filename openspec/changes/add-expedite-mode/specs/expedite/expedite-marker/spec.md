# Delta Spec: expedite/expedite-marker

## Purpose

Defines the `factory:expedite` marker label: what it means, who may apply it,
which issues it may sit on, how task sub-issues inherit it, and what removing
it does. The transitions it drives are specified in `expedite/auto-chaining`;
the gate it stops at is specified in `expedite/staging-gate`.

## ADDED Requirements

### Requirement: The expedite marker is orthogonal to state

`factory:expedite` SHALL be a marker label, not a state: it sits alongside the
issue's single `factory:*` state label, is excluded from state computations
(like `factory:blocked` and `factory:in-progress`), and no transition outside
the expedite auto-advance map depends on it. It SHALL be created by
`scripts/setup-labels.sh` alongside the existing labels.

#### Scenario: Marker does not disturb state accounting

- **WHEN** an epic carries `factory:design-ready` and `factory:expedite`
- **THEN** the issue's state is reported as `factory:design-ready`, and every
  non-expedite routing rule behaves exactly as if the marker were absent

### Requirement: Applying the marker is authorized

An `expedite` key in `.github/factory-approvers.json` SHALL list the users who
may apply `factory:expedite`. An empty or absent list SHALL fall back to any
owner, member or collaborator. When the label is applied by a sender not so
authorized, the router SHALL remove it and comment naming the required
approvers — identical in shape to the existing revert of hand-applied gate
labels — exempting the factory's own App writes.

#### Scenario: Unauthorized application is reverted

- **WHEN** `.github/factory-approvers.json` lists `"expedite": ["lead"]` and
  user `dev` applies `factory:expedite` to an epic
- **THEN** the label is removed and a comment names @lead as the required
  approver, and no auto-advance occurs

#### Scenario: Authorized application is honored immediately

- **WHEN** an authorized user applies `factory:expedite` to an epic at
  `factory:spec-ready`
- **THEN** the marker stays and the auto-advance map acts on the current state
  in that same routing pass (gate G1 auto-approves, per `expedite/auto-chaining`)

### Requirement: Scope — epics only, post-spec effect

`factory:expedite` SHALL be honored on requirement (epic) issues. It SHALL be
refused — removed with an explanatory comment — on release trackers
(`factory:release`), profile issues (`factory:profile`) and issues carrying
`factory:fast-track` (the fast lane already has no pre-G3 gates). Applied to
an epic that has not yet produced a spec (backlog, intake), the marker SHALL
remain but cause no action: intake and gate G0 are never affected, and the
first expedited action is the G1 auto-approval at `factory:spec-ready`.

#### Scenario: Pre-spec application is dormant, not refused

- **WHEN** `factory:expedite` is applied to an epic in `factory:intake`
- **THEN** nothing runs at application time, and when the Intake Analyst later
  moves the epic to `factory:spec-ready`, gate G1 auto-approves

#### Scenario: Refused on a fast-lane issue

- **WHEN** `factory:expedite` is applied to an issue labelled
  `factory:fast-track`
- **THEN** the marker is removed with a comment explaining the fast lane has
  no gates to expedite before G3

### Requirement: Tasks inherit expedite from their epic

A task sub-issue (`task(<epic>)` title) SHALL be treated as expedited exactly
when its epic currently carries `factory:expedite`, resolved via the task's
title and `Part of <owner>/<repo>#<n>` marker — the same resolution, cross-repo
constraints and PAT fallback behavior as the task-closed re-dispatch. The
label SHALL NOT be copied onto task issues by the factory. A cross-repo lookup
that cannot be made (no cross-repo access) SHALL result in no auto-advance and
a comment on the task naming the manual control, never a silent stall.

#### Scenario: Task auto-advances while its epic is expedited

- **WHEN** a task of an expedited epic reaches `factory:in-review`
- **THEN** the Reviewer is started automatically without a human touch

#### Scenario: Removing the marker from the epic stops its tasks too

- **WHEN** `factory:expedite` is removed from the epic while a task sits at
  `factory:in-test`
- **THEN** no further auto-advance occurs on the epic or any of its tasks, and
  the normal next-step controls apply from each issue's current state

### Requirement: Removal is safe and unrestricted

Any owner, member or collaborator MAY remove `factory:expedite` at any time.
Removal SHALL stop future auto-advance only: in-flight role runs finish
normally, no state label changes, and the pipeline continues under the normal
human gates from wherever each issue stands. The factory SHALL comment once on
removal, restating the current state's normal controls.

#### Scenario: Removal mid-chain

- **WHEN** the marker is removed while an implementer run is live on a task
- **THEN** the run completes and moves the task to `factory:in-review`, and the
  Reviewer is NOT auto-started; the standard in-review next-step notice applies
