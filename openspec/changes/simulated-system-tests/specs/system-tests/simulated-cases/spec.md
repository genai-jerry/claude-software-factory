# Delta Spec: system-tests/simulated-cases

## Purpose

Lets an epic's system test cases run in the repository's simulated environment on the staging
merge, and brings each case's result back to the epic, its test issue and gate G3.

## ADDED Requirements

### Requirement: The simulate block

A repository SHALL opt in with a `simulate` block in `.github/factory-testing.json` naming:
- `pack`: the scenario directory;
- `guide`: the simulation guide;
- `status_context`: the commit status the simulator's run posts;
- `run_repo`: the repository whose workflow runs it;
- `simulators`: the simulator repositories, each with what it simulates.

Without the block, the Test Planner, the Dispatcher and the router SHALL behave exactly as today.

#### Scenario: No block, no change
- **WHEN** a repository's testing policy has no `simulate` block
- **THEN** every case is written as today, no simulated-tests task is opened, and no simulator
  result is read

### Requirement: Each case is sorted as simulated or manual

With the block, the Test Planner SHALL give each case `Execution: simulated` or `Execution: manual`,
and a manual case SHALL carry the reason it cannot be simulated, in the guide's words. A case SHALL
be simulated only when every expected result can be checked from what the simulators received or
the product's API answers.

#### Scenario: A case that needs a real phone
- **WHEN** a case's expected result is what the phone agent sounds like on a call-screening phone
- **THEN** the case is `Execution: manual` with the reason "real audio on a real phone"

#### Scenario: A case over ten days of calls
- **WHEN** a case checks that a lead is tried on days 1, 2, 9 and 10
- **THEN** the case is `Execution: simulated`

### Requirement: One simulated-tests task per epic

When at least one case is simulated, the Test Planner SHALL open one task sub-issue,
`task(<epic>): simulated tests — ST-<a>..ST-<b>`, and append it to `tasks.md`. It SHALL be exempt
from the task cap, `Blocked by` the code tasks its cases depend on and the loader task, and SHALL
otherwise be an ordinary task. Its work:
- one scenario file per simulated case at `<pack>/<epic>-st-<n>.json`;
- each file's `covers` field naming `<owner>/<repo>#<epic> ST-<n>`;
- the data sets the scenario uses, kept inside the pack.

On a revision, the existing task SHALL be updated rather than a second one opened.

#### Scenario: The task is opened beside the loader task
- **WHEN** the Test Planner finishes a plan with 30 simulated cases in a repository with a
  `simulate` block
- **THEN** one simulated-tests task exists for the epic, blocked by the code tasks those cases
  depend on, and it is listed in `tasks.md`

#### Scenario: A scenario that cannot start fails before staging
- **WHEN** a scenario file in the task's pull request cannot reach the simulator's first call
  through the product's own gates
- **THEN** the repository's test suite fails on that pull request, and the task does not pass QA

### Requirement: Simulator gaps become tasks

When a simulated case needs behaviour no simulator has (a call script, a reply), the Test Planner
SHALL open a task in that simulator's repository naming the behaviour and the cases that need it,
and the simulated-tests task SHALL be `Blocked by` it.

#### Scenario: A voicemail call script
- **WHEN** a simulated case needs a call that ends in voicemail, and the call simulator has no such
  script
- **THEN** a task in the call simulator's repository asks for a `voicemail` call script, and the
  simulated-tests task is blocked by it

### Requirement: Results are read back from the simulator's run

When the commit status named by `status_context` finishes on a commit of the integration branch,
and an epic at `factory:in-staging` in that repository has its integration merge in that commit's
history, the factory SHALL read the run's report. For each scenario whose `covers` names one of
that epic's cases, it SHALL:
- label the case `factory:test-passed` on a pass, or `factory:test-failed` on a fail or error;
- comment with the run's link, the commit, and for a failure each failing step as the report words
  it.

It SHALL post one summary on the epic: how many simulated cases passed and failed, how many manual
cases are still open, and any other scenario in the pack that failed in that run, named as a
regression. It SHALL NOT open a fix task. A run already recorded SHALL NOT be recorded again.

#### Scenario: A simulated case passes
- **WHEN** the run after #667's staging merge reports `667-st-21` as passed
- **THEN** the issue for ST-21 is labelled `factory:test-passed`, with a comment linking the run

#### Scenario: A simulated case fails
- **WHEN** the run reports `667-st-25` failed at step 7
- **THEN** the issue for ST-25 is labelled `factory:test-failed`, with a comment quoting step 7's
  failure, and no fix task is opened

#### Scenario: A later run passes after a fix
- **WHEN** a case is `factory:test-failed` from an earlier run, and a later run on the integration
  branch passes it
- **THEN** the case becomes `factory:test-passed`, and the comment names both runs

#### Scenario: A regression in another epic's scenario
- **WHEN** a run that carries #667 fails `retry-gaps`, which covers no case of #667
- **THEN** #667's summary names `retry-gaps` as a regression failing in this run

### Requirement: A person still decides

A person's `Test Passed` or `Test Failed` on a simulated case SHALL be accepted as it is on a manual
case, and SHALL win over the simulated verdict until a later run records a newer one. `Test Failed`
SHALL open a fix task as it does today.

#### Scenario: A person sends a simulated failure for a fix
- **WHEN** a staging approver comments `Test Failed` on a case labelled `factory:test-failed` by a
  run, and it has no fix yet
- **THEN** the fix task is opened as for a manual case

### Requirement: A fix task from a failure, optionally expedited

A comment of exactly `Test Failed, expedite` on a failed case, from a person on the `expedite`
approvers list, SHALL open the fix task exactly as `Test Failed` does and label that fix task alone
`factory:expedite`. The task then advances itself up to gate GS (FACTORY.md §4a); the epic's
marker is not touched. From anyone else, it SHALL open the fix task without the marker and say why
it was not expedited.

#### Scenario: An expedited fix
- **WHEN** an expedite approver comments `Test Failed, expedite` on ST-25 after a simulated failure
- **THEN** a fix task for ST-25 is opened with `factory:expedite`, and its Implementer starts
  without anyone pressing Start

#### Scenario: Not an expedite approver
- **WHEN** a collaborator who is not an expedite approver comments `Test Failed, expedite`
- **THEN** the fix task is opened without `factory:expedite`, and the reply says the expedite part
  needs an expedite approver

### Requirement: Adoption on an epic already planned

A staging approver's comment of exactly `Simulate tests` on an epic, in a repository with a
`simulate` block, SHALL run the Test Planner to sort the existing cases (keeping their numbers),
open the simulated-tests task and any gap tasks, and say on the epic how many cases became
simulated and which stay manual and why.

#### Scenario: #667
- **WHEN** a staging approver comments `Simulate tests` on beacon-api#667
- **THEN** each of its 39 cases is marked simulated or manual with a reason, and one simulated-tests
  task and its gap tasks are opened

### Requirement: Compass shows the verdicts at G3

The Test board and the production decision SHALL show each case as simulated or manual, its
verdict, and for a simulated verdict the run it came from. The production decision SHALL show the
counts of simulated passed, simulated failed and manual still open, and any regression the latest
run named. A failed case SHALL show its failing step in the runner's words and SHALL offer
**Create fix task** and **Create fix task (expedite)**, which post `Test Failed` and
`Test Failed, expedite` on the case as the signed-in person. A case whose fix is already open
SHALL show the fix instead of the buttons.

#### Scenario: The production decision for #667
- **WHEN** a person opens #667's production decision after its simulated run
- **THEN** they see the simulated and manual counts, each failing case with its step, a link to
  the run, and the two fix buttons on each failing case
