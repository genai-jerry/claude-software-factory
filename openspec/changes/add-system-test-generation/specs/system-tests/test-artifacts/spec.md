# Delta Spec: system-tests/test-artifacts

## Purpose

Defines the system test plan and test data artifacts of an OpenSpec change:
what they contain, how each test case is traced to the spec scenarios it
proves and the tasks it depends on, what test data may and may not hold, and
how OpenSpec is told about them through the factory's workflow schema.

## ADDED Requirements

### Requirement: The system test plan artifact

Every epic that runs the Test Planner SHALL carry a
`system-tests/test-plan.md` in its change folder
(`openspec/changes/<epic>-<slug>/system-tests/test-plan.md`), on the same
branch as `tasks.md` and `design.md`. It SHALL contain, in this order: a
**Scope** section naming what the plan proves and what it deliberately leaves
to the automated suite; an **Environment** section naming where the cases
run (the epic's preview environment when the profile's `deploy` block defines
one, else staging) and what a tester needs in order to reach it; a **Test
cases** section; and a **Traceability** table listing every WHEN/THEN
scenario of the change's `specs/` with the test case identifiers that cover
it. The plan is black-box: it MUST be derivable from `proposal.md` and
`specs/` alone and MUST NOT cite `design.md`, module names, or any
implementation detail.

#### Scenario: A plan exists beside the design

- **WHEN** the Test Planner finishes on an epic whose spec has three
  capabilities
- **THEN** `system-tests/test-plan.md` exists in the change folder on the
  `factory/<epic>-design` branch, and every scenario in the three delta specs
  appears in its Traceability table with at least one test case identifier

#### Scenario: A scenario with no case is a defect of the plan

- **WHEN** a spec scenario appears in the Traceability table with no test
  case identifier
- **THEN** the plan is incomplete: the Test Planner MUST add a case or record
  in Scope why that scenario is proven by the automated suite alone, naming
  the scenario, before it hands off

### Requirement: The shape of a test case

Each test case SHALL be a `### ST-<n>: <title>` heading followed by these
fields, each on its own line: `Covers:` one or more scenario references in
the form `<capability-path>/<Requirement name>/<Scenario name>`; `Depends
on:` the `tasks.md` task identifiers whose code the case exercises (`none`
when the case exercises behaviour no task changes, for example a regression
check); `Data:` the data set identifiers it uses, or `none`; `Execution:`
`manual` (the default) or `manual, automatable` when the planner judges an
automated equivalent worth writing; `Preconditions:`; numbered `Steps:`; and
`Expected:` the observable result, stated so a tester can decide pass or fail
without interpretation. Identifiers SHALL be stable: a revised plan MUST
never renumber an existing case; a withdrawn case keeps its number and is
marked `Withdrawn:` with a reason.

#### Scenario: Every field present

- **WHEN** a test case is written
- **THEN** it carries `Covers`, `Depends on`, `Data`, `Execution`,
  `Preconditions`, `Steps` and `Expected`, and its `Covers` references
  resolve to headings that exist in the change's `specs/`

#### Scenario: Revision keeps identifiers

- **WHEN** the plan is revised after a spec change and one case no longer
  applies
- **THEN** that case keeps its `ST-<n>` identifier and is marked `Withdrawn:`
  with the reason, and new cases take numbers after the highest existing one

### Requirement: The test data artifact

Every epic that runs the Test Planner SHALL carry a
`system-tests/test-data.md` beside the plan, containing one `### DS-<n>:
<name>` section per data set with these fields: `Used by:` the test cases
that reference it; `Setup:` how a tester loads it — API calls, UI steps, or a
seed command the repo already has (from the profile's `qa_notes`), never a
command that has to be invented; `Records:` the data itself, as a table or a
fenced block, or a relative path under `system-tests/data/` when it is a
file; and `Teardown:` how to remove it. Every error-path or boundary scenario
in the spec SHALL have at least one data set that provokes it. All test data
SHALL be synthetic: no production data, no real personal data, no secrets or
credentials, no live payment instruments — exactly the rule FACTORY.md §8
already applies to every artifact.

#### Scenario: A data set per error scenario

- **WHEN** a spec scenario describes a rejected input (an invalid, missing or
  out-of-range value)
- **THEN** `test-data.md` contains a data set whose records include that
  input, and the test case that covers the scenario names it in `Data:`

#### Scenario: Real data is refused

- **WHEN** a test case would need a real customer record, a production
  identifier or a live credential to run
- **THEN** the plan names a synthetic stand-in and how to create it in
  `Setup:`, and the Reviewer at gate G2 treats any real value in
  `system-tests/` as a blocking finding

### Requirement: The factory workflow schema

The factory SHALL ship an OpenSpec workflow schema named `factory` under
`templates/openspec/schemas/factory/` — a fork of the package's `spec-driven`
schema with two artifacts appended: `test-plan` (generates
`system-tests/test-plan.md`, requires `specs` and `tasks`) and `test-data`
(generates `system-tests/test-data.md`, requires `test-plan`), each with a
template and an instruction block that states the format above. A consuming
repo adopts it by copying the directory to `openspec/schemas/factory/` and
setting `schema: factory` in `openspec/config.yaml`; `openspec status` and
`openspec validate` then see the two artifacts. The Test Planner SHALL
produce identical files whether or not the repo has adopted the schema —
reading the templates from its own factory checkout when
`openspec instructions test-plan` reports no such artifact — so the schema
is an aid to tooling, never a precondition of the pipeline. The `apply`
block SHALL be unchanged (`requires: [tasks]`, `tracks: tasks.md`): test
cases are tracked as sub-issues, not as checkboxes.

#### Scenario: Adopted schema serves the instructions

- **WHEN** a repo has `openspec/schemas/factory/` and `schema: factory`, and
  an agent runs `openspec instructions test-plan --change <c> --json`
- **THEN** the response carries the factory's template and instruction for
  the plan, and `openspec status --change <c>` lists `test-plan` and
  `test-data` with their completion state

#### Scenario: Unadopted schema changes nothing about the files

- **WHEN** a repo still uses `schema: spec-driven` and the Test Planner runs
- **THEN** the same `system-tests/test-plan.md` and `test-data.md` are
  written from the factory's shipped templates, and the run reports that the
  repo has not adopted the schema without blocking on it

### Requirement: Where the artifacts land when the design PR has gone

The Test Planner writes onto the open `factory/<epic>-design` branch when
there is one (`test-planner`). For an epic whose design PR has already merged
— every epic adopted after gate G2 — there is no such branch, and the plan
SHALL instead go on `factory/<epic>-tests`, cut from the epic's **home
branch** (the epic branch under `epics: true`, else the branch that carries
the change folder, FACTORY.md §6a), with one PR titled `test(<epic>): system
test plan` based on that same branch. The PR SHALL cc the `design` approvers
— they own document review for this epic — and say what merging it releases.
It SHALL never be based on the default branch while the epic has a home
branch, exactly like every other document PR.

A plan SHALL become authoritative only when it is **merged on the home
branch**: until then its cases exist as sub-issues but no case is runnable
(`manual-test-tasks`). This is one rule for both paths rather than a special
case for adoption — on the normal path the plan merges at gate G2, long
before any task assembles, so the rule is invisible there; on an adopted
epic whose tasks are already built it is what stops a plan nobody has read
from putting cases in front of testers.

#### Scenario: Adopted epic gets its own document PR

- **WHEN** the Test Planner runs on an epic at `factory:design-approved`
  whose design PR merged last week, under `epics: true`
- **THEN** it commits the plan and data on `factory/<epic>-tests` cut from
  `factory/epic-<epic>`, opens a PR based on that branch, and cc's the
  `design` approvers

#### Scenario: Merging the plan is what releases its cases

- **WHEN** that PR is still open and every task a case depends on is
  `factory:on-epic`
- **THEN** the case stays pending, and the Dispatcher's summary says the plan
  is not merged yet and names the PR

#### Scenario: Open design PR is still the target

- **WHEN** the Test Planner runs on an epic at `factory:planned` whose
  `factory/<epic>-design` PR is open
- **THEN** it commits onto that branch as usual and opens no second PR

### Requirement: The artifacts travel with the change

`system-tests/` SHALL be treated as change content in every respect: it
lives on the epic's home branch beside the other documents (FACTORY.md §6),
merges through the design PR at gate G2, is read by every later stage from
"the first branch that carries the change folder" (§6a), and is archived
with the change folder by the Ops Monitor. It is never copied into an issue
body: test sub-issues link to it, exactly as task sub-issues link to
`tasks.md`.

#### Scenario: Read from the epic branch

- **WHEN** a tester opens a test sub-issue of an epic under `epics: true`
- **THEN** its body links `system-tests/test-plan.md` on the epic branch and
  names the case identifier, and carries no steps or data of its own
