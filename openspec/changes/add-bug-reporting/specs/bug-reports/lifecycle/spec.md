# Delta Spec: bug-reports/lifecycle

## Purpose

Defines what happens to a bug report once it exists: the task filed to fix it,
the states it moves through, who confirms the repair, and how an open bug is
counted at gate GS.

## ADDED Requirements

### Requirement: Three bug states

`scripts/setup-labels.sh` SHALL create `factory:bug-open` (raised; its fix
task is in flight), `factory:bug-retest` (the fix is assembled; a human
confirms the repair) and `factory:bug-verified` (confirmed — the report
closes), plus the kind marker `factory:bug`. The three SHALL be ordinary
states, mutually exclusive with every other `factory:*` state, and SHALL only
ever sit on a `bug(<epic>)` sub-issue. A bug report SHALL never carry
`factory:ready`, `factory:in-review`, `factory:in-test`,
`factory:ready-to-ship` or `factory:on-epic`; a code state applied to one by
hand SHALL be reverted with a reply naming the fix task as where the work is.
`handbook/next-step.json` SHALL answer all three.

#### Scenario: Code state reverted

- **WHEN** a human applies `factory:ready` to a `bug(<epic>)` report
- **THEN** the label is removed and the reply names the task filed to fix it,
  and says the report moves on the Dispatcher and a tester's verdict

### Requirement: The fix is an ordinary task

Raising a bug SHALL file `task(<epic>): fix bug #<n> — <title>` at
`factory:ready` in the epic's repo, quoting the report and carrying the
`Part of #<epic>` marker, and SHALL append `Blocked by #<fix>` to the report.
The task SHALL be started, implemented, reviewed, tested and assembled exactly
as any other task of that epic, under whatever approvals and `factory:expedite`
the epic already carries — so its merge lands on the epic branch (§6b), or on
the integration branch for an epic with none.

#### Scenario: Ordinary start

- **WHEN** a bug is raised on a non-expedited epic
- **THEN** the fix task sits at `factory:ready` and its notice names the
  `implementation` approvers and the `Approved` comment that starts it

#### Scenario: Expedited epic

- **WHEN** a bug is raised on an epic carrying `factory:expedite`
- **THEN** the fix task's notice says the implementer starts on its own, and
  no approval is asked for

### Requirement: Re-test and confirmation

The Dispatcher SHALL move a bug at `factory:bug-open` to
`factory:bug-retest` once every task it is `Blocked by` has reached its
assembled state (`factory:on-epic` with an epic branch, `factory:in-staging`
without one, or closed either way), assigning the `testers` (falling back to
`implementation`). A `testers` approver commenting exactly `Test Passed` on a
bug at `factory:bug-retest` SHALL close it at `factory:bug-verified` and
re-run the Dispatcher on the epic; any collaborator commenting exactly
`Test Failed` SHALL file another fix task and return the **same** report to
`factory:bug-open`. Neither verdict SHALL have any effect on a bug in another
state, and the reply SHALL say what the bug is waiting for instead.

#### Scenario: Repair confirmed

- **WHEN** a `testers` approver comments `Test Passed` on a bug at
  `factory:bug-retest`
- **THEN** the report closes at `factory:bug-verified` and the epic is
  re-dispatched, because the last confirmation may complete it

#### Scenario: Still there

- **WHEN** any collaborator comments `Test Failed` on a bug at
  `factory:bug-retest`
- **THEN** another fix task is filed, the report returns to
  `factory:bug-open` with a second `Blocked by` marker, and the reply says
  this is the same bug rather than a new one

#### Scenario: Verdict too early

- **WHEN** either verdict is commented on a bug at `factory:bug-open`
- **THEN** nothing changes and the reply says the report becomes
  `factory:bug-retest` when the task fixing it is assembled

### Requirement: An open bug holds gate GS

Where `bug_reports` is on, `mode` is `"gate"` and the repo has epic branches,
an epic SHALL NOT be complete while any of its bugs is open, and `Approved` on
an epic at `factory:epic-ready` SHALL be refused while one is — naming each
open bug and its fix, and the two ways out (close the report, or
`mode: advisory`). Raising a bug SHALL NOT move an epic backwards out of a
state it has already been granted. Under `"advisory"`, and for a repo with no
epic branch, open bugs SHALL hold nothing and SHALL be listed as evidence in
the gate notice, the assembly report and the promotion PR.

#### Scenario: Gate held

- **WHEN** a `staging` approver comments `Approved` on an epic at
  `factory:epic-ready` that has a bug at `factory:bug-open`
- **THEN** no Release Manager runs, the epic keeps `factory:epic-ready`, and
  the reply lists the bug and its fix

#### Scenario: Advisory mode releases

- **WHEN** the same world has `"mode": "advisory"`
- **THEN** the Release Manager starts, and the open bug travels as evidence in
  the integration and promotion reports

#### Scenario: Closed as not a defect

- **WHEN** a human closes a bug report by hand
- **THEN** the epic is re-dispatched, because a closed bug holds nothing and
  may have been the last thing the epic was waiting on
