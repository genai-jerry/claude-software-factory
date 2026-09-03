# Design: System Test Generation

## Context

What the factory proves today, and where:

| Evidence | Produced by | Read at |
|---|---|---|
| Spec scenarios (WHEN/THEN) | Intake | G1, then every later stage |
| Scenario → automated test mapping, suite green | QA, per task PR | `factory:ready-to-ship`, the assembly report |
| Health checks after each merge | Release Manager | Assembly and integration reports |
| Smoke checks and soak | Ops | Closure |

Nothing in that table is a human exercising the assembled epic. OpenSpec's
`spec-driven` schema (`@fission-ai/openspec` 1.8) has four artifacts and no
test artifact; its only statements about testing are "each scenario is a
potential test case" and "each task MUST state how to verify completion". Its
extension point is a project-local workflow schema
(`openspec/schemas/<name>/schema.yaml`, created with `openspec schema fork
spec-driven <name>`): artifacts have `id`, `generates`, `template`,
`instruction` and `requires`, and `openspec instructions <id> --change <c>
--json` serves them to an agent. `openspec schema` is marked experimental,
which is why the pipeline must not *depend* on it (D2).

The mechanics this change touches are the same four that expedite moved
together, plus one:

- **The routing decision table** — the `route` script in
  `.github/workflows/factory-pipeline.yml` and its port
  `orchestrator/src/factory_orchestrator/router.py`, pinned by
  `orchestrator/conformance/`.
- **In-run chaining** — the Actions `architect-chain` / `expedite-chain` jobs
  and the orchestrator's `chain_node`.
- **The trace contract** — `handbook/next-step.json` and its two renderers.
- **The Console** — `packages/core` label catalogue and derivations.
- **The Dispatcher prompt** — the one role that resolves `Blocked by`
  markers; test tasks ride on that.

One constraint shaped the release mechanism. Under `epics: true` a task PR
merges onto the epic branch, and GitHub closes a `Closes #N` issue only for a
merge into the default branch — so the "task sub-issue closes → re-dispatch"
trigger in FACTORY.md §2a does not fire for those merges. The Console
already documents that a task "closes only at the end of the line". Test
tasks cannot wait for an event that never comes, hence D6.

## Goals / Non-Goals

**Goals**

- A test plan and test data in the change folder, written from the finalized
  spec, reviewed at the gate that already reviews the plan and design.
- Each test case a task a human executes once its code is assembled, with
  pass/fail recorded on the issue like every other factory decision.
- The result counted before gate GS, so the staging approver sees a matrix,
  not a promise.
- Opt-in by one file; both engines, fixtures, hand-off wording and Console
  in lockstep; no new state outside GitHub labels and the change folder.

**Non-Goals**

- Generating automated test *code* from the plan. QA's scenario → test
  mapping is unchanged; `Execution: manual, automatable` is a hint for a
  later change, not a work item here.
- An epic-level "in system test" state. The epic stays
  `factory:design-approved` while its tests run (the Dispatcher's guard
  depends on it); the Console derives "assembled, 3/5 tests passed" from the
  children, as it already derives "Building 2/4".
- Holding gate G3 on tests. G3 is a merge click the factory cannot refuse.
- A durable regression suite under `openspec/specs/`. The plan archives with
  its change; folding cases into a living suite is a separate proposal.
- Test management tooling outside GitHub (no TestRail, no spreadsheets). The
  issue thread is the test record.

## Decisions

### D1 — Two artifacts, black-box, from the spec

`system-tests/test-plan.md` and `system-tests/test-data.md` are derived from
`proposal.md`, `specs/` and `tasks.md`, never from `design.md` or code. Two
reasons. System tests describe behaviour a user can observe, which is exactly
the boundary the spec already draws ("if the implementation can change
without changing externally visible behavior, it does not belong in the
spec"); a plan that cites modules would rot with the first refactor. And it
lets the Test Planner run *before* the Architect, so the design can respond
to the plan — a seed command for DS-3, a preview environment the plan needs
— instead of the plan bending to the design.

Alternatives: one combined `system-tests.md` (rejected — data sets are shared
across cases and edited on their own cadence; two artifacts give OpenSpec
two `requires` edges to check); a `tests/` directory of one file per case
(rejected — a tester reads the whole plan, and one file keeps the
traceability table next to the cases it indexes).

### D2 — The `factory` workflow schema is an aid, not a dependency

The factory ships `templates/openspec/schemas/factory/` (a fork of
`spec-driven` plus `test-plan` and `test-data`), and the setup guide
recommends adopting it: `openspec status` then tracks the two artifacts and
`openspec instructions test-plan` serves the format to any agent. But the
Test Planner writes the same files from templates in its own factory checkout
when the repo has not adopted it. `openspec schema` is experimental, repos
are on whatever OpenSpec version they installed, and a pipeline that fails
because a consuming repo's `openspec/config.yaml` still says `spec-driven`
would be a setup trap of the kind §9 exists to avoid. The `apply` block is
untouched: test cases are tracked as sub-issues (D4), not `tasks.md`
checkboxes, so `/opsx:apply` never sees them.

### D3 — A thirteenth role, chained Planner → Test Planner → Architect

The Test Planner is its own prompt rather than a section of the Planner's.
Roles get their own model resolution, timeout and `factory:in-progress`
span; the Planner's prompt is already the longest of the pre-G2 roles; and a
repo that turns system tests off should run byte-identical prompts, which a
conditional section inside `planner.md` cannot promise. It runs between the
two because it needs `tasks.md` (for `Depends on:`) and the Architect
benefits from the plan (D1).

Chaining reuses the existing mechanism exactly. The Actions
`architect-chain` job becomes two steps with the same gate — Planner reached
`factory:planned` → run `testplanner` (when the policy enables it) → still
`factory:planned` → run `architect` — with a shared checkout step; no PAT is
involved because it is in-run, like today. The orchestrator's `chain_node`
gets one more `if c["role"] == ...` hop. `factory:planned` stays deliberately
unmapped so neither engine double-fires anything. A manual start of
`testplanner` on a `factory:planned` epic is the retry path, as for every
role.

Alternative: run it after the Architect at `factory:design-ready` (rejected —
an expedited epic approves G2 the moment it reaches that state, and the plan
would race the gate).

### D4 — Test cases are sub-issues with `Blocked by` markers

Every non-withdrawn case becomes `test(<epic>): ST-<n> <title>` in the epic's
repo, with one `Blocked by` line per depended-on task sub-issue. This buys
the whole release mechanism for free: the Dispatcher already resolves those
markers, in-repo and cross-repo, and already treats an unlabelled child as
"waiting". The only new rule it learns is *what "done" means for a
dependency of a test*: the assembled state (`factory:on-epic`, or
`factory:in-staging` without an epic branch), not "closed or merged". A new
title prefix rather than `task(<epic>)` because the router, the Console and
the Planner's cap all key on `task(`; test sub-issues must not be dispatched
to an Implementer, must not count against ~10, and must render as a
different kind.

Cross-repo epics keep their test sub-issues in the coordination repo:
system tests are end to end, and the epic's repo is where the
`factory:epic-ready` flip and the GS notice happen.

### D5 — Three states and two comments

`factory:manual-test` → (`Test Passed`) → `factory:test-passed`, or →
(`Test Failed`) → `factory:test-failed` → (fix lands, Dispatcher) →
`factory:manual-test`. Three labels rather than reusing existing ones,
because every existing task state has a role behind it and the auto-advance
map would start that role. Closing the sub-issue on pass, rather than only
labelling, keeps the Console's done-count honest and gives the Ops Monitor
nothing extra to close.

Comments rather than labels as the human control, because that is the
factory's grammar for every other human verdict (`Approved`, `Review Done`,
`Plan release`), the Console already knows how to post a literal comment as
the user, and the thread then holds the verdict next to the tester's
evidence. `Test Passed` is authorised against a new `testers` key —
empty ⇒ any owner/member/collaborator, the same default as every gate — and
`Test Failed` from anyone with write access, on the principle expedite
already states: an action that only adds work or puts humans back in the
loop needs no list.

### D6 — Release → Dispatcher chain, in both engines

After a Release phase-1 run lands anything, the engine runs the Dispatcher
on the epic in the same run. The Actions engine adds a `dispatch-chain` job
modelled on `architect-chain` (`needs: [route, agent]`, `if: role ==
'release'`, checks the epic is `factory:design-approved`); the orchestrator
appends `{"role": "dispatch", "issue": epic}` in `chain_node` after a
successful `release`. This is what releases test tasks, and it also releases
code-task dependents that the close-event path could not (Context). The
Dispatcher is idempotent — it skips any child that already carries a state —
so an extra run costs one summary comment. Expedite's existing
`ready-to-ship → release` hop composes with it unchanged: the chained
Dispatcher's fan-out of newly-ready tasks is exactly what `chain_node` and
`expedite-chain` already do after a dispatch.

### D7 — Gate GS counts tests through the Dispatcher's completeness check

Rather than teaching the router to compute "all code on-epic and all tests
passed" on a `Test Passed` event, the router routes the **Dispatcher** to the
epic when a pass lands and the epic is `factory:design-approved`. The
Dispatcher's step 4 already answers "is every child finished?" and already
makes the `factory:epic-ready` flip; it gains one clause (test children must
be `factory:test-passed` under `mode: gate`) and one more line in its
summary (the test matrix). One place decides completeness, three paths reach
it (task close, chained after a landing, last pass). The Release Manager's
step 5 gets the same clause so the two never disagree.

`mode: advisory` exists for estates that want the plan and the tasks but not
the hold — a pilot, or a repo whose testers are outside the approvers'
working hours — and it is one `if` in each of those two prompts.

### D8 — Without an epic branch, evidence only

Under `epics: false` the first shared branch is the integration branch,
reached only after gate GS, so the tests can only run on staging, between GS
and G3. G3 is a human merge the factory cannot hold; pretending to gate it
would mean either a merge list withheld by a role that has already been
asked to post it, or a router that refuses a click it does not own. The
honest position is the one the Release Manager already takes for a
`required: false` repo: say plainly what is unverified, in the promotion PR
body and the merge-list comment. `mode` is documented as having no effect
here.

### D9 — Fix tasks are ordinary tasks

`Test Failed` opens `task(<epic>): fix ST-<n> — <title>` at `factory:ready`
directly (it has no dependencies by construction, so the Dispatcher would
only re-derive that) and appends `Blocked by #<fix>` to the test sub-issue.
Everything after that is the existing pipeline: implementation approvers or
expedite start it, Reviewer and QA check it, the Release Manager lands it,
the chained Dispatcher (D6) sees the test's dependency assembled and
re-releases it. The two-round rework cap applies to the fix task as to any
task. Nothing new to route, nothing new to show.

Alternative: send the depended-on code task back to `factory:ready`
(rejected — that task is merged on the epic branch; reopening it would
either fork its branch or rewrite epic history, and its PR is closed).

## Risks / Trade-offs

- [Plans that restate the spec] → The template forces `Steps:` and
  `Expected:` as concrete actions and observations, and the traceability
  table makes a one-case-per-scenario plan visible as such; G2 review is the
  backstop, and the `design` approvers are told the plan is part of what
  they approve.
- [Test data that leaks real values] → Synthetic-only is a spec requirement,
  a Reviewer finding at G2, and a line in the Test Planner's guardrails; the
  factory's existing no-secrets rule (§8) already covers the artifact.
- [Testers never notified] → `factory:manual-test` assigns and @-mentions
  the `testers` list, falling back to the `implementation` list when absent
  (someone always owns it), and the Console surfaces the case as a needs-you
  item; the hand-off notice names the two comments.
- [Epic stuck at design-approved with tests nobody runs] → In `gate` mode
  that is the intended hold, and the Console's epic status says "assembled ·
  waiting on 3 tests" with the testers named; `advisory` is the escape, and
  the policy can be flipped mid-epic (the next Dispatcher run re-evaluates).
- [Chain lengthens the G1 → G2 run] → One more role of a few minutes inside a
  45-minute job; the Test Planner is a document role, not a code role.
- [Two Dispatcher runs race (task close and chained landing)] → Both are
  idempotent and label-guarded; the worst case is two summary comments. The
  orchestrator's ledger and the Actions `concurrency` group already
  serialise runs per issue.
- [Fixture growth] → Around a dozen new fixtures; they are the contract, and
  both routers already run every fixture in CI.

## Migration Plan

1. Land the change with the policy file absent everywhere: no behaviour
   changes. `scripts/setup-labels.sh` creates the three labels on its next
   run (harmless without the policy).
2. Per repo that opts in: copy `templates/factory-testing.json` to
   `.github/`, re-run `setup-labels.sh`, add `testers` to
   `factory-approvers.json` and `testplanner` to `factory-models.json`,
   optionally adopt the OpenSpec schema.
3. Epics already past G2 when the policy lands have no plan and no test
   sub-issues; they finish as today. Running `testplanner` by hand on one
   writes a plan and opens sub-issues, which the next Dispatcher run picks
   up — documented as the adoption path for an in-flight epic.
4. Rollback: remove the policy file. Existing test sub-issues stay as
   history; the Dispatcher ignores `test(` children when the policy is off,
   and `Test Passed` / `Test Failed` answer "not enabled here".

## Open Questions

- Whether `Execution: manual, automatable` cases should let QA cite an
  automated test as a pass without a human (a later change; the field is
  recorded now so the plan does not need revising then).
- Whether a per-repo `testers` list is enough for an estate whose testers
  are a team outside the repo's collaborators (they must be collaborators to
  be assignable — same constraint as every approver list).
