# Delta Spec: branching/artifact-routing

## Purpose

Defines, for every kind of PR the factory opens and every pipeline stage that
reads a repo, which branch it bases on, merges into, and checks out — under
both the epic-branch policy (`epics: true`) and the legacy policy
(`epics: false`).

## ADDED Requirements

### Requirement: Document PRs merge into the epic branch

When `epics` is `true`, the spec PR (head `factory/<epic>-spec`) and the
shared plan+design PR (head `factory/<epic>-design`) SHALL base on the epic
branch `factory/epic-<epic>`, and their gate approvals (G1, G2) SHALL
squash-merge them into the epic branch. When `epics` is `false`, document PRs
SHALL continue to base on the default branch. Document PRs SHALL never base on
the integration branch under either policy.

#### Scenario: Spec PR targets the epic branch

- **WHEN** `epics` is `true` and the Intake Analyst opens the spec PR for
  epic #42
- **THEN** the PR's base branch is `factory/epic-42`, not the default branch

#### Scenario: Gate approval merges the document into the epic branch

- **WHEN** an approver applies gate G1 (or comments `Approved` on the issue in
  `factory:spec-ready`)
- **THEN** the spec PR is squash-merged into `factory/epic-42`, and the change
  folder `openspec/changes/42-<slug>/` is present on `factory/epic-42`

#### Scenario: Legacy policy unchanged

- **WHEN** `epics` is `false` and the Intake Analyst opens a spec PR
- **THEN** the PR's base branch is the default branch, as before this change

### Requirement: Task branches cut from and merge into the epic branch

When `epics` is `true`, task branches `factory/<task-issue>-<slug>` SHALL be
cut from the epic branch, and each task PR SHALL base on the epic branch. A
task PR based on the default branch or directly on the integration branch
SHALL be treated by the Reviewer and QA as a blocking finding, exactly as a
default-branch-based PR is treated today. When `epics` is `false`, task
branches SHALL continue to cut from and merge into the integration branch.

#### Scenario: Implementer bases a task PR on the epic branch

- **WHEN** `epics` is `true` and the Implementer starts task #57 of epic #42
- **THEN** branch `factory/57-<slug>` is cut from `factory/epic-42` and its
  draft PR's base is `factory/epic-42`

#### Scenario: Wrong base is a blocking review finding

- **WHEN** a task PR of epic #42 is based on the integration branch or the
  default branch while `epics` is `true`
- **THEN** the Reviewer or QA sends the task back with the base branch named
  as the reason, and the PR is not marked `factory:ready-to-ship`

### Requirement: Pipeline stages check out the epic branch

When `epics` is `true`, every stage that reads the epic's change folder or
code after intake — Planner, Architect, Implementer, Reviewer, QA, Release
(phase 1), Ops — SHALL operate on a checkout of the epic branch, since the
approved spec and design exist only there until promotion. When `epics` is
`false`, stages SHALL continue to check out the default branch.

#### Scenario: Planner reads the approved spec from the epic branch

- **WHEN** gate G1 passes for epic #42 with `epics: true` and the Planner runs
- **THEN** the Planner reads `openspec/changes/42-<slug>/` from
  `factory/epic-42`, and commits `tasks.md` on a branch cut from
  `factory/epic-42`

#### Scenario: An approved spec is never invisible to later stages

- **WHEN** any post-intake stage runs for epic #42 with `epics: true`
- **THEN** the change folder it reads includes every document merged at an
  earlier gate of that epic

### Requirement: Fast-track and promotion routing are unchanged

Fast-track PRs (no epic) SHALL continue to base on the integration branch
under either policy. Promotion to the default branch SHALL continue to happen
only via an integration-branch → default-branch promotion PR merged by a human
at gate G3. The epic-branch policy SHALL NOT introduce any new path to the
default branch.

#### Scenario: Fast-track skips the epic layer

- **WHEN** an issue labelled `factory:fast-track` is implemented while
  `epics` is `true`
- **THEN** its PR bases on the integration branch, with no epic branch created

#### Scenario: Only promotion PRs reach the default branch

- **WHEN** any factory-authored PR targets the default branch
- **THEN** it is an integration → default promotion PR; an epic branch is
  never merged directly into the default branch
