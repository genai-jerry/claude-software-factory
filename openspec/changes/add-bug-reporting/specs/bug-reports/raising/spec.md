# Delta Spec: bug-reports/raising

## Purpose

Defines how a defect found while testing an epic becomes a `bug(<epic>)`
sub-issue of that epic: the policy that enables it, the two entry points, what
is accepted, and what is refused with which reason.

## ADDED Requirements

### Requirement: The policy key

`.github/factory-testing.json` SHALL carry an optional `bug_reports` key
(`true` / `false`). When absent it SHALL follow `system_tests`, so a repo that
enabled system test cases can raise bugs without a second decision. An
explicit value SHALL win in both directions: `false` keeps the cases and
refuses bugs; `true` with `"system_tests": false` enables bugs with no Test
Planner and no cases. `mode` SHALL govern bugs exactly as it governs cases.

#### Scenario: Absent key follows the cases

- **WHEN** a repo has `{"system_tests": true}` and no `bug_reports` key
- **THEN** a `Bug` comment on an epic under test raises a report

#### Scenario: Bugs without a plan

- **WHEN** a repo has `{"system_tests": false, "bug_reports": true}`
- **THEN** no Test Planner runs and no case exists, and a `Bug` comment on an
  epic under test still raises a report

#### Scenario: Policy off

- **WHEN** a repo has no `.github/factory-testing.json`, or has
  `{"bug_reports": false}`
- **THEN** `Bug` is answered once, saying bug reports are not enabled here and
  naming the key that enables them, and nothing is filed

### Requirement: The `Bug` comment control

A collaborator SHALL raise a bug by commenting on the epic, or on one of its
task or test sub-issues, with a first line of exactly `Bug`, `Bug: <title>` or
`Bug — <title>`, and the report on the lines beneath it. This SHALL be the
only factory control that reads past its first line. Without a title, the
first line of the report SHALL become the title, truncated at 80 characters.
A first line that continues into other words (`Bug fix pushed`) SHALL NOT be a
control.

#### Scenario: Report with a title

- **WHEN** a collaborator comments `Bug: the discount is ignored` followed by
  steps and observations on the epic
- **THEN** a `bug(<epic>): the discount is ignored` sub-issue is opened at
  `factory:bug-open` carrying the reporter, the epic and the report quoted

#### Scenario: No report

- **WHEN** the comment is `Bug` with nothing under it
- **THEN** nothing is filed and the reply asks for what they saw, what they
  did and what they expected, showing the shape of a good report

#### Scenario: Raised from a case

- **WHEN** the control is used on a `test(<epic>)` case's thread
- **THEN** the report is raised against the **epic**, carries
  `Seen on: #<case>`, and the case's own state is untouched — a bug is not a
  case verdict

#### Scenario: Not a collaborator

- **WHEN** the commenter has no owner, member or collaborator association
- **THEN** nothing is filed and the reply says which access raising a bug
  needs

### Requirement: The `factory:bug` label

An issue labelled `factory:bug` — at filing, from
`.github/ISSUE_TEMPLATE/factory-bug.yml`, or by a maintainer labelling an
issue somebody already wrote — SHALL be adopted in place as that epic's bug
report: retitled `bug(<epic>): <title>`, given the `Part of #<epic>` marker
and `factory:bug-open`, **keeping its own body**. `factory:bug` SHALL be a
kind marker: it stays for the life of the report and never reads as a state.
The epic SHALL be resolved from an `Epic: #<n>` line or the issue form's
`### Epic` heading. Applying the label SHALL be treated as privileged (it
requires write access); a report *filed* with the label SHALL be adopted only
when its author has owner, member or collaborator association.

#### Scenario: Label applied later

- **WHEN** a maintainer applies `factory:bug` to an issue whose body names an
  epic under test
- **THEN** the issue is retitled `bug(<epic>): ...`, moves to
  `factory:bug-open`, keeps the body it had, and a fix task is filed

#### Scenario: No epic named

- **WHEN** the labelled issue names no epic this repository has
- **THEN** the issue is left exactly as it is, and the reply asks for an
  `Epic: #<n>` line and says that an issue with no epic is an ordinary issue

#### Scenario: Filed by an outsider

- **WHEN** an issue labelled `factory:bug` is opened by someone with no write
  access
- **THEN** nothing is filed, the issue keeps its title, and the reply says a
  maintainer can raise it by re-applying the label

#### Scenario: The factory's own label write

- **WHEN** the engine itself applies `factory:bug` while raising a report
- **THEN** the resulting `labeled` event adopts nothing — the run that applied
  it has already done the work

### Requirement: What a bug is accepted against

A bug SHALL be accepted only against an **epic** at `factory:design-approved`,
`factory:epic-ready` or `factory:in-staging`, and refused with the reason
otherwise: earlier than `factory:design-approved` the reporter has a
requirement (intake is upstream); on a shipped or closed epic it is a new
issue or `factory:incident`; on a release tracker, the profile issue or a
fast-track issue there is no epic branch to fix into. A report whose epic
lives in another repository SHALL be refused with that repository named — a
report lives beside the epic it is raised against.

#### Scenario: Too early

- **WHEN** `Bug` is used on an epic at `factory:planned`
- **THEN** nothing is filed and the reply says the epic has built nothing yet
  and that what they have is a requirement

#### Scenario: Already shipped

- **WHEN** `Bug` is used on a closed epic, or one at `factory:deployed`
- **THEN** nothing is filed and the reply points at an ordinary issue, or
  `factory:incident` where production is affected
