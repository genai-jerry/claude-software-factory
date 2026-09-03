# Add System Test Generation (test plan, test data, manual test tasks)

## Why

The factory proves an epic three ways today: the Reviewer reads the diff,
QA maps every WHEN/THEN scenario to an *automated* test and runs the suite,
and the Release Manager runs the profile's `deploy.health_checks` after each
merge. Nothing in that chain is a person exercising the assembled system the
way its users will — with real screens, real data shapes, and the scenarios
that only make sense end to end. Teams do that testing anyway; they do it off
the books, from a spreadsheet somebody wrote by reading the spec, and the
factory neither knows it happened nor waits for it. Gate GS is opened on the
strength of a green suite and an assembly report.

OpenSpec has no artifact for this. The default `spec-driven` schema
(`proposal → specs → design → tasks`) says only that "each scenario is a
potential test case" and that every task must state how it is verified; it
defines no test plan, no test data, and no place for a human's verdict. It
does, however, define the extension point: a project-local **workflow
schema** (`openspec schema fork spec-driven <name>`) can add artifacts with
their own templates, instructions and dependency edges, and `openspec
instructions <artifact>` then serves them to whichever agent writes them.
That is the standard way to add content to a change folder, and this change
uses it rather than inventing a parallel one.

What is missing is therefore three things, in the factory's own terms: a
**content** artifact (the system test plan and its data, in the change folder
where every other artifact of the epic lives), a **role** that writes it from
the finalized spec, and a **state** that carries each test case through a
human's hands as a task — released once the code it exercises is on the epic
branch, and counted before the epic is called ready for staging.

## What Changes

- **Two new OpenSpec artifacts** in every epic's change folder, produced
  after the spec is approved and reviewed at gate G2 alongside the plan and
  design: `system-tests/test-plan.md` (numbered, traceable test cases: each
  cites the `capability/requirement/scenario` it covers, the tasks it depends
  on, its data set, preconditions, steps and expected result) and
  `system-tests/test-data.md` (named, synthetic data sets the cases reference,
  with how to load and tear them down). The factory ships the schema that
  declares them — `templates/openspec/schemas/factory/` , a fork of
  `spec-driven` with two artifacts appended (`test-plan` requires `specs` and
  `tasks`; `test-data` requires `test-plan`) — as an optional install step;
  the role writes the same files whether or not the consuming repo has
  adopted the schema.
- **A new role, the Test Planner** (`/factory:testplanner`, stage 2a), chained
  between the Planner and the Architect in the existing G1 → G2 run. It reads
  the approved `proposal.md` + `specs/` and the Planner's `tasks.md`, writes
  the two artifacts on the shared `factory/<epic>-design` branch, and mirrors
  every test case into a **test sub-issue** titled `test(<epic>): ST-<n>
  <title>`, whose body carries the case's scenario references and one
  `Blocked by` marker per code task it depends on — the same machine-readable
  dependency form the Dispatcher already reads. Test cases are black-box:
  they derive from the spec, never from `design.md`, so the Architect can read
  the plan and design for it (seedable data, a preview environment) rather
  than the other way round.
- **Three new task states** for test sub-issues, created by
  `scripts/setup-labels.sh` (25 → 28 labels): `factory:manual-test` (the
  covering code is assembled; a human runs this case), `factory:test-passed`
  (terminal) and `factory:test-failed` (a fix task is in flight). A test task
  is never dispatched to an Implementer, Reviewer or QA: it moves by two new
  strict-match comments, `Test Passed` and `Test Failed`, and by the
  Dispatcher releasing it when the code tasks it names are on the epic branch
  (`factory:on-epic`), or on staging (`factory:in-staging`) for an epic
  without an epic branch.
- **`Test Failed` files the fix.** The router opens a `task(<epic>): fix
  ST-<n> — <title>` sub-issue at `factory:ready` carrying the failure
  comment, appends `Blocked by #<fix>` to the test task and flips it to
  `factory:test-failed`. The fix walks the ordinary implement → review → QA →
  assemble path, honouring the implementation approvers and expedite exactly
  as any task, and when it lands the Dispatcher returns the test to
  `factory:manual-test` for a re-run.
- **Gate GS counts the tests.** With the policy's `mode` at `gate` (the
  default once system tests are on), an epic with an epic branch flips to
  `factory:epic-ready` only when every code task is `factory:on-epic` *and*
  every test task is `factory:test-passed`; the last `Test Passed` re-runs the
  Dispatcher, whose existing "epic complete" check makes the flip. `advisory`
  keeps today's flip and lists open tests in the assembly report instead.
  Under `epics: false` the code reaches a shared branch only at GS, so test
  tasks are released at `factory:in-staging` and their results are evidence in
  the promotion PR body: gate G3 is a merge click the factory cannot hold, and
  this change does not pretend otherwise.
- **A `testers` approver key** in `.github/factory-approvers.json`: assigned
  and @-mentioned when a test task becomes runnable, and the list `Test
  Passed` is authorised against (empty ⇒ any owner/member/collaborator).
  `Test Failed` is honoured from any collaborator — a failure only adds work,
  which is always safe.
- **Opt-in by one file.** `.github/factory-testing.json` (`{"system_tests":
  true, "mode": "gate"}`; template in `templates/`). Absent, the Test Planner
  never runs, no test sub-issues exist, and every existing repo behaves
  byte-for-byte as it does today.
- **A Release → Dispatcher chain in both engines.** After a Release phase-1
  run lands a task on the epic branch, the engine runs the Dispatcher on the
  epic in the same run. This is what releases test tasks — and it closes a
  gap that predates this change: the §2a re-dispatch fires on a task *closing*,
  which GitHub does only for a PR merged to the default branch, so under
  `epics: true` dependents of a task merged onto the epic branch were released
  only by hand.
- **Existing epics can adopt it.** An epic that passed gate G2 before system
  tests were enabled has no plan and no chain left to write one, so a
  collaborator comments exactly `Plan tests` on it (or dispatches
  `role: testplanner`, the scripted path for adopting many at once) and the
  Test Planner runs on the spot. It is allowed from `factory:planned` through
  `factory:in-staging`, leaves the epic in whatever state it found, and is
  refused with a reason before the task breakdown exists, on shipped epics,
  and on issues with no spec to test. With the design PR already merged the
  plan lands on a `factory/<epic>-tests` PR onto the epic's home branch,
  cc'ing the `design` approvers. A case becomes runnable only once its plan is
  **merged** — one rule for both paths, and what stops an unread plan
  reaching testers. Adoption never moves an epic backwards: on one already at
  `factory:epic-ready` or later the verdicts are evidence on the gate, exactly
  as they are for an epic with no epic branch, rather than a hold that revokes
  a state the factory already granted.
- **Expedite is unchanged and stops short of a human's test.**
  `factory:manual-test` is absent from the auto-advance map; an expedited
  epic assembles itself and then waits for its testers exactly as it waits
  for gate GS.
- **Surface updates:** FACTORY.md (§2 stage table, §2a triggers, §2b
  approver table, §3 states, §4 gate GS wording, §5 OpenSpec conventions,
  new §4b on system tests, §9 setup, §10 footprint — "twelve role prompts"
  becomes thirteen), `handbook/next-step.json` (three new entries),
  `templates/factory-models.json`, the `planner`/`architect`/`dispatch`/
  `release`/`qa`/`ops` role prompts where they count tasks or name the chain,
  the wiki state diagram, and the Factory Console (companion change
  `add-system-test-tasks-console` in `software-factory-view`: the three
  states, the `test(` task kind, tester attention items, Pass/Fail actions,
  the plan in the artifact reader, the test matrix on the GS panel).

## Capabilities

### New Capabilities

- `system-tests/test-artifacts`: the `test-plan.md` and `test-data.md`
  artifacts — format, identifiers, traceability, data rules, where they live
  and how OpenSpec learns about them (the `factory` workflow schema).
- `system-tests/test-planner`: the Test Planner role — when it runs, what it
  reads, what it writes, the test sub-issues it opens, and how G2 reviews it.
- `system-tests/manual-test-tasks`: the test task lifecycle — the three
  states, release by the Dispatcher, `Test Passed` / `Test Failed`, the fix
  task, gate GS accounting under both branch policies, the policy file, the
  `testers` list, and what expedite does not touch.

### Modified Capabilities

- `expedite/staging-gate`: the `factory:epic-ready` precondition gains the
  test-task clause under `mode: gate`; the Release → Dispatcher chain is the
  mechanism that reaches it.

## Impact

- **Adoption is per-epic and deliberately not batched.** Each plan is a
  document somebody should read before its cases reach testers, so there is
  no "plan tests for every open epic" control; the manual dispatch is the
  scripted path for an estate that wants one anyway.
- **Opt-in, no behavioural change without the policy file.** Repos that add
  `.github/factory-testing.json` also re-run `scripts/setup-labels.sh`
  (25 → 28 labels), add `testplanner` to `.github/factory-models.json`
  (missing roles already fall back to `claude-sonnet-5`), and may add a
  `testers` list to `factory-approvers.json`. Adopting the OpenSpec schema
  (`openspec/schemas/factory/` + `schema: factory` in `openspec/config.yaml`)
  is recommended and optional.
- **Longer G1 → G2 run.** One more role in the chain (minutes), one more
  document in the design PR for the G2 approver to read.
- **Both routers, the fixtures, the next-step table and the Console move in
  lockstep,** as the engine contract requires; new conformance fixtures pin
  every new branch.
- **Cross-repo epics:** test sub-issues live in the epic's (coordination)
  repo, since system tests are end to end; their `Blocked by
  <owner>/<repo>#N` markers point at sibling-repo code tasks, which the
  Dispatcher already resolves over `FACTORY_CROSS_REPO_TOKEN`.
