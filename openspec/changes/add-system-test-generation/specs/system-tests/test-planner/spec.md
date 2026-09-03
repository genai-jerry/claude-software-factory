# Delta Spec: system-tests/test-planner

## Purpose

Defines the Test Planner, the role that turns an approved spec into a system
test plan, its test data and one test sub-issue per case: when it runs in
the pipeline, what it reads and writes, and how gate G2 reviews its output.

## ADDED Requirements

### Requirement: The role and where it runs

A thirteenth role prompt, `commands/testplanner.md` (`/factory:testplanner`,
stage 2a), SHALL run on an epic at `factory:planned` — after the Planner has
written `tasks.md` and before the Architect writes `design.md` — whenever the
consuming repo's `.github/factory-testing.json` sets `system_tests: true`.
Both engines SHALL chain it in the same run as the Planner and Architect,
gated exactly as the Architect is today: the Planner must have reached
`factory:planned`, and the Test Planner must leave the epic at
`factory:planned` for the Architect to proceed. Without the policy file, or
with `system_tests` false, the chain SHALL be Planner → Architect exactly as
today and no test artifacts or sub-issues SHALL exist. The role SHALL also be
startable by hand on any epic in the states the adoption requirement below
names (Run workflow, or the Console) and SHALL be idempotent: a re-run on an
epic that already has a plan revises it, keeping identifiers, rather than
writing a second one.

#### Scenario: Chained between Planner and Architect

- **WHEN** gate G1 opens on an epic in a repo whose policy sets
  `system_tests: true` and the Planner reaches `factory:planned`
- **THEN** the same run starts the Test Planner on the epic, and the
  Architect starts only after the Test Planner finishes with the epic still
  at `factory:planned`

#### Scenario: Policy absent keeps today's chain

- **WHEN** gate G1 opens on an epic in a repo with no
  `.github/factory-testing.json`
- **THEN** the run chains Planner → Architect with no Test Planner, opens no
  test sub-issues, and writes no `system-tests/`

#### Scenario: Blocked Planner blocks the chain

- **WHEN** the Planner ends at `factory:blocked` or splits the epic
- **THEN** neither the Test Planner nor the Architect runs, as today

### Requirement: Adoption on an epic already in flight

An epic that passed gate G2 before system tests were enabled — or before this
change existed — has no plan and no test sub-issues, and the chain that would
have written them is long finished. The factory SHALL therefore let a human
ask for one: a comment whose body is exactly `Plan tests` on such an epic
SHALL start the Test Planner on it. It is a strict match, like every other
factory comment control, and it is unrestricted (any owner, member or
collaborator) — writing a test plan only adds documents and work, which is
always safe, and the plan itself is reviewed before any case becomes runnable
(`test-artifacts`). `workflow_dispatch` with `role: testplanner` and the epic
number SHALL do the same thing, so an estate can adopt many epics with a
script rather than a comment each.

The run SHALL be allowed on an epic at `factory:planned`,
`factory:design-ready`, `factory:design-approved`, `factory:epic-ready` or
`factory:in-staging`, and SHALL leave the epic in whatever state it found —
it is a document run, and it never advances, reverts or gates the epic. It
SHALL be refused, with a comment naming the reason, on an epic earlier than
`factory:planned` (there is no `tasks.md` to derive `Depends on:` from — the
reply names the Planner as what to wait for), on a `factory:deployed` or
closed epic (that work has shipped; a defect there is an incident or a new
issue), on task and test sub-issues, on release trackers, on the profile
issue, on `factory:fast-track` issues (no change folder), and in a repo whose
`.github/factory-testing.json` does not enable system tests.

#### Scenario: Adopting on a mid-implementation epic

- **WHEN** a collaborator comments `Plan tests` on an epic at
  `factory:design-approved` whose tasks are half implemented
- **THEN** the Test Planner runs, writes the plan and data, opens the test
  sub-issues, and the epic is still `factory:design-approved` when it
  finishes

#### Scenario: Adopting on an assembled epic

- **WHEN** the same comment lands on an epic at `factory:epic-ready`
- **THEN** the Test Planner runs and the epic stays `factory:epic-ready` —
  the cases become runnable when the plan merges, and they are evidence on
  the gate rather than a hold (see `manual-test-tasks`)

#### Scenario: Too early is refused with the reason

- **WHEN** `Plan tests` is commented on an epic at `factory:spec-approved`
- **THEN** nothing runs and the reply says there is no task breakdown yet and
  that the Planner produces one at `factory:planned`

#### Scenario: Refused where there is no spec to test

- **WHEN** `Plan tests` is commented on a `factory:fast-track` issue, a
  release tracker or the profile issue
- **THEN** nothing runs and the reply names why that issue has no system test
  plan

#### Scenario: Scripted adoption across an estate

- **WHEN** an operator dispatches `role: testplanner` for each of five
  in-flight epics
- **THEN** each run writes that epic's plan and opens its sub-issues, with no
  comment on any epic required

### Requirement: What it reads and what it writes

The Test Planner SHALL read `proposal.md`, `specs/` and `tasks.md` from the
change folder on the epic's home branch, plus the profile's `qa_notes` and
`deploy` block (for seed commands and the preview environment); it SHALL NOT
read `design.md` (which does not exist yet) and SHALL NOT infer behaviour
from code. It SHALL write `system-tests/test-plan.md` and
`system-tests/test-data.md` per the `test-artifacts` capability, committed to
the existing `factory/<epic>-design` branch the Planner opened, so that one
design PR carries `tasks.md`, `system-tests/` and, after the Architect,
`design.md`. It SHALL derive each case's `Depends on:` from the Planner's
task → scenario mapping in `tasks.md`: a case depends on every task that
serves a scenario it covers.

#### Scenario: One PR for plan, tests and design

- **WHEN** the Architect marks the design PR ready after the Test Planner ran
- **THEN** the PR's diff contains `tasks.md`, `system-tests/test-plan.md`,
  `system-tests/test-data.md` and `design.md`, and gate G2 approves all four
  together

#### Scenario: Dependencies follow the task mapping

- **WHEN** `tasks.md` says task 2.1 serves scenario S and task 2.3 serves
  scenario T, and case ST-4 covers S and T
- **THEN** ST-4 lists `Depends on: 2.1, 2.3` and its sub-issue carries a
  `Blocked by` marker for each of the two task sub-issues

### Requirement: Test sub-issues

For every non-withdrawn case the Test Planner SHALL open (or, on a re-run,
update) one sub-issue in the epic's own repo titled `test(<epic>): ST-<n>
<title>`, with a body that links `system-tests/test-plan.md` on the home
branch, names the case identifier, lists its `Covers:` references, and
carries one machine-readable `Blocked by #N` (or `Blocked by
<owner>/<repo>#N` for a sibling-repo task) line per depended-on task
sub-issue — the same forms FACTORY.md §7 defines for task sub-issues. It
SHALL carry no `factory:*` state label at creation, no steps and no data.
Test sub-issues SHALL NOT count against the Planner's ~10-task cap and SHALL
NOT be mirrored into `tasks.md`. The Test Planner SHALL post the case list
on the epic as a checklist comment, beside the Planner's task tree.

#### Scenario: One sub-issue per case, none for withdrawn

- **WHEN** the plan has cases ST-1 to ST-6 and ST-3 is withdrawn
- **THEN** five `test(<epic>)` sub-issues exist, ST-3 has none (or its
  existing one is closed with the withdrawal reason), and each open one links
  the plan and carries its `Blocked by` markers

#### Scenario: Cross-repo dependency marker

- **WHEN** ST-2 depends on a task whose sub-issue the Planner opened in a
  sibling repo
- **THEN** ST-2's sub-issue carries `Blocked by <owner>/<sibling>#N`, and the
  Dispatcher resolves it over `FACTORY_CROSS_REPO_TOKEN` exactly as it does
  for a task's cross-repo dependency

### Requirement: Gate G2 reviews the plan

Gate G2 SHALL be the human review of the system test plan and its data. The
`design` approvers are cc'd by the Architect as today; the Architect's
hand-off comment SHALL name the plan and its case count so the approver
knows it is part of what they are approving. A real credential, production
identifier or personal record under `system-tests/` SHALL be a blocking
finding at G2. An expedited epic (§4a) approves G2 itself and therefore
accepts the plan unread — this is the trade expedite already makes for
`tasks.md` and `design.md`, and it is stated on the epic in the G2
self-approval notice.

#### Scenario: Plan named at the gate

- **WHEN** the Architect flips the epic to `factory:design-ready`
- **THEN** its hand-off comment says that the design PR also carries a system
  test plan of N cases and M data sets awaiting the same approval

#### Scenario: Expedited G2 accepts the plan

- **WHEN** an expedited epic reaches `factory:design-ready`
- **THEN** gate G2 approves itself as today and the self-approval notice says
  the system test plan was merged unreviewed and remains editable on the
  epic branch

### Requirement: Model and surfaces

The role SHALL be routed like the Planner and Architect (`claude-fable-5` →
`claude-opus-5` → `claude-sonnet-5` in `templates/factory-models.json`),
because a wrong test plan misdirects every human tester after it. It SHALL be
listed in FACTORY.md's stage table, the plugin's role count, the wiki's
state diagram and the Console's role vocabulary.

#### Scenario: Model chain

- **WHEN** the workflow resolves a model for `testplanner`
- **THEN** it probes the same preference chain as `planner`, and an absent
  `testplanner` key falls back to `claude-sonnet-5` as any missing role does
