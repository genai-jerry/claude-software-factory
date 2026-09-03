# Delta Spec: system-tests/manual-test-tasks

## Purpose

Defines the lifecycle of a test sub-issue — a system test case a human
executes against the assembled epic — from its release by the Dispatcher
through pass, fail, fix and re-test, and how the outcome is counted before an
epic is called ready for staging.

## ADDED Requirements

### Requirement: The policy file

`.github/factory-testing.json` in the consuming repo SHALL enable and shape
system testing: `system_tests` (`true` / `false`; absent file ⇒ `false`) and
`mode` (`"gate"`, the default when the file is present, or `"advisory"`). An
absent or unparseable file SHALL leave every existing behaviour unchanged. A
template SHALL ship in `templates/factory-testing.json` and the file SHALL be
listed in FACTORY.md §10's footprint table as optional.

#### Scenario: Absent file is off

- **WHEN** a repo has no `.github/factory-testing.json`
- **THEN** no Test Planner runs, no test states are applied, `Test Passed`
  and `Test Failed` comments are answered with "system tests are not enabled
  here" and nothing else, and the `factory:epic-ready` precondition is exactly
  today's

#### Scenario: Invalid file is off

- **WHEN** the file exists but does not parse
- **THEN** it is treated as absent, and the first run that reads it says so
  once on the issue it was routing

### Requirement: Three test states

`scripts/setup-labels.sh` SHALL create three state labels that apply only to
`test(<epic>)` sub-issues: `factory:manual-test` (the code this case depends
on is assembled; a human runs it), `factory:test-passed` (the case passed —
terminal, the sub-issue closes) and `factory:test-failed` (the case failed; a
fix task is in flight). They are states, mutually exclusive with every other
`factory:*` state, and a test sub-issue SHALL never carry `factory:ready`,
`factory:in-review`, `factory:in-test`, `factory:ready-to-ship` or
`factory:on-epic`. A test sub-issue with no state label is pending: its
dependencies are not yet assembled, exactly as an unlabelled task sub-issue
is waiting on its dependencies. The label count moves 25 → 28.

#### Scenario: Labels created

- **WHEN** `scripts/setup-labels.sh` runs against a repo
- **THEN** the three labels exist with the documented colours and
  descriptions, and the Console's label catalogue carries the same three

#### Scenario: Never a code state

- **WHEN** any actor applies `factory:ready` to a `test(<epic>)` sub-issue
- **THEN** the router reverts it with a comment saying test sub-issues are
  released by the Dispatcher to `factory:manual-test` and never implemented

### Requirement: The Dispatcher releases test tasks

The Dispatcher SHALL treat `test(<epic>)` sub-issues as a second kind of
child. For each one that carries no state label and whose every `Blocked
by` target has reached its **assembled state** — `factory:on-epic` when the
epic has an epic branch, `factory:in-staging` when it does not — it SHALL
apply `factory:manual-test`, assign the `testers` approvers and post a
comment naming the case, the plan, the environment and the two comments that
move it. A test sub-issue with `Depends on: none` is released together with
the first wave once any task of the epic is assembled. A test sub-issue in
`factory:test-failed` whose fix task has reached its assembled state SHALL be
returned to `factory:manual-test` with a "re-test" comment. An unreachable
cross-repo dependency SHALL be treated as not assembled, as today.

#### Scenario: Released when its code is on the epic branch

- **WHEN** ST-4 depends on tasks #21 and #22, #21 is `factory:on-epic` and #22
  reaches `factory:on-epic`, and the Dispatcher runs
- **THEN** ST-4's sub-issue gets `factory:manual-test`, the `testers` are
  assigned and @-mentioned, and the comment names the plan on the epic branch

#### Scenario: Not released while a dependency is in review

- **WHEN** ST-4 depends on #21 (`factory:on-epic`) and #22
  (`factory:in-review`) and the Dispatcher runs
- **THEN** ST-4 stays unlabelled and the Dispatcher's summary lists it as
  waiting on #22

#### Scenario: Released on staging without an epic branch

- **WHEN** the epic has no epic branch, its tasks reach `factory:in-staging`
  after gate GS, and the Dispatcher runs
- **THEN** every test sub-issue whose dependencies are `factory:in-staging`
  gets `factory:manual-test`, with the environment named as staging

### Requirement: The Release → Dispatcher chain

After a Release Manager phase-1 run moves any task to `factory:on-epic` (or a
phase-1b run moves tasks to `factory:in-staging`), both engines SHALL run the
Dispatcher on the epic in the same run — the Actions engine as an in-run
chained job like the existing planner → architect chain, the orchestrator in
its chain node — so tasks freed by the merge, test sub-issues included, are
released without waiting for an issue-close event that a merge onto the epic
branch never emits. The chain SHALL run whether or not system tests are
enabled; without them it releases only code tasks, which is a correction the
§2a re-dispatch was meant to make and could not under `epics: true`.

#### Scenario: Landing a task runs the Dispatcher

- **WHEN** a Release phase-1 run lands task #22 on the epic branch and marks
  it `factory:on-epic`
- **THEN** the same run starts the Dispatcher on the epic, which releases
  every task and test whose dependencies that landing completed

#### Scenario: Chain is a no-op with nothing to release

- **WHEN** the Dispatcher chained after a landing finds no unlabelled child
  whose dependencies are all assembled
- **THEN** it says so once on the epic and changes no label

### Requirement: Test Passed and Test Failed

A comment whose body is exactly `Test Passed` on a `test(<epic>)` sub-issue
at `factory:manual-test`, from a user in the `testers` list (empty ⇒ any
owner/member/collaborator), SHALL flip it to `factory:test-passed`, close it,
and record the verdict and its author in a receipt comment. A comment whose
body is exactly `Test Failed` from any owner/member/collaborator SHALL flip
it to `factory:test-failed` and file the fix (next requirement). Either
comment on a test sub-issue in any other state, or from an unauthorised user
for `Test Passed`, SHALL be answered with the state it is in and the control
that applies, and change nothing. Both are strict matches, like `Approved`:
"Test Passed, mostly" is a comment. A tester's evidence — screenshots,
observed values — belongs in the same thread and is not parsed.

#### Scenario: Pass closes the case

- **WHEN** a `testers` member comments `Test Passed` on ST-4 at
  `factory:manual-test`
- **THEN** ST-4 flips to `factory:test-passed`, is closed, and the receipt
  names the author and the case

#### Scenario: Unauthorised pass is refused

- **WHEN** a user outside a non-empty `testers` list comments `Test Passed`
- **THEN** the router replies naming the testers and changes nothing

#### Scenario: Pass in the wrong state does nothing

- **WHEN** anyone comments `Test Passed` on a pending (unlabelled) test
  sub-issue
- **THEN** the router replies that the case is not runnable yet and which
  tasks it waits on, and changes nothing

### Requirement: A failure files the fix

On `Test Failed`, the router SHALL open a sub-issue in the epic's repo titled
`task(<epic>): fix ST-<n> — <title>` whose body links the test sub-issue and
the change folder, quotes the failure comment, carries `Part of` when the
epic is elsewhere, and lists no `Blocked by`; apply `factory:ready` to it
and post the same start notice the Dispatcher posts (implementation
approvers cc'd, or the expedite wording when the epic is expedited); append
`Blocked by #<fix>` to the test sub-issue's body; and flip the test
sub-issue to `factory:test-failed` with a comment naming the fix. The fix
task then follows the ordinary task lifecycle — implement, review, QA,
assemble — under whatever approvals and expedite the epic has. Because the
new task is a `task(<epic>)` sub-issue, the Planner's cap and the epic's
task count in the Console include it. A second `Test Failed` on a case
already at `factory:test-failed` SHALL be refused with the fix task named.

#### Scenario: Fix task opened at ready

- **WHEN** a collaborator comments `Test Failed` on ST-4 at
  `factory:manual-test`
- **THEN** a `task(<epic>): fix ST-4 — <title>` sub-issue exists at
  `factory:ready` quoting the comment, ST-4 carries `Blocked by #<fix>` and
  `factory:test-failed`, and ST-4's thread names the fix task

#### Scenario: Fix landing re-releases the case

- **WHEN** the fix task reaches `factory:on-epic` and the chained Dispatcher
  runs
- **THEN** ST-4 returns to `factory:manual-test` with a re-test comment, and
  its previous failure stays in the thread

#### Scenario: Expedited fix starts itself

- **WHEN** `Test Failed` is commented on a case of an expedited epic
- **THEN** the fix task is opened at `factory:ready` and its Implementer
  starts without an `Approved`, per the auto-advance map

### Requirement: Gate GS counts the tests

Under `mode: gate` and with an epic branch, "the epic is complete" — the
condition under which the Release Manager (phase 1, step 5) or the Dispatcher
(step 4) flips the epic to `factory:epic-ready` — SHALL require every
`task(<epic>)` sub-issue at `factory:on-epic` **and** every open
`test(<epic>)` sub-issue at `factory:test-passed`. When the last code task
lands and tests remain, the Release Manager SHALL post the assembly report,
say the epic is assembled and waiting on N system tests, and leave the epic
at `factory:design-approved`; the last `Test Passed` SHALL route the
Dispatcher to the epic, whose completeness check then makes the flip. Under
`mode: advisory` the flip is today's, and the assembly report and the GS
hand-off notice list the open and failed cases. In both modes the epic's
`factory:epic-ready` notice SHALL carry the test matrix (case → verdict →
author) as evidence for the `staging` approver.

#### Scenario: Last pass flips the epic

- **WHEN** every code task of an epic is `factory:on-epic`, one test remains
  at `factory:manual-test`, and a tester comments `Test Passed` on it
- **THEN** the router runs the Dispatcher on the epic, which flips it to
  `factory:epic-ready` and posts the GS notice with the full test matrix

#### Scenario: Assembled but untested does not open the gate

- **WHEN** the Release Manager lands the last code task under `mode: gate`
  and two tests are still at `factory:manual-test`
- **THEN** the epic stays `factory:design-approved`, the assembly report says
  it waits on those two cases, and no `staging` approver is asked for
  anything

#### Scenario: Advisory mode reports instead of holding

- **WHEN** the same landing happens under `mode: advisory`
- **THEN** the epic flips to `factory:epic-ready` as today and the GS notice
  lists the two open cases as unverified

### Requirement: Without an epic branch, tests are evidence for G3

Under `epics: false` (or for a pre-flip epic with no epic branch) the code
reaches a shared branch only at gate GS, so test sub-issues SHALL be released
at `factory:in-staging` and run on staging. The factory SHALL NOT hold gate
G3 on them — G3 is a human's merge click — but the Release Manager SHALL list
the test matrix, open cases included, in every promotion PR body and in the
G3 merge-list comment, and SHALL say plainly when it is posting a merge list
with unverified cases. `mode: gate` and `mode: advisory` behave identically
here, and the policy file's documentation SHALL say so.

#### Scenario: Promotion PR carries the matrix

- **WHEN** the Release Manager opens promotion PRs for an epic without an
  epic branch and one case is still `factory:manual-test`
- **THEN** each PR body lists every case with its verdict and marks that one
  as unverified, and the merge-list comment repeats the warning

### Requirement: Expedite stops at a human's test

`factory:manual-test`, `factory:test-passed` and `factory:test-failed` SHALL
be absent from the auto-advance map. An expedited epic assembles itself,
releases its tests through the chained Dispatcher, and then waits for its
testers exactly as it waits for gate GS; the marker's dormant/end-of-chain
notice SHALL say so when tests are enabled.

#### Scenario: Expedite on a runnable test does nothing

- **WHEN** `factory:expedite` is applied to an epic whose remaining open
  children are test sub-issues at `factory:manual-test`
- **THEN** the router starts nothing and says the epic is waiting on N
  system tests, naming the testers

### Requirement: The hand-off table

`handbook/next-step.json` SHALL gain entries for the three states, rendered
by both engines: `factory:manual-test` names the testers, the plan and the
two comments; `factory:test-failed` names the fix task and says the case
re-opens when it lands; `factory:test-passed` says the case is done and what
the epic waits on. Existing entries for `factory:on-epic` and
`factory:design-approved` SHALL mention system tests only when the policy
enables them, via a `tested` wording variant selected the way the
`expedited` variant already is.

#### Scenario: Both renderers agree

- **WHEN** a test sub-issue reaches `factory:manual-test` under either engine
- **THEN** the posted notice is byte-identical between
  `scripts/say_next_step.py` and `factory_orchestrator.next_step`, and names
  the `testers` list
