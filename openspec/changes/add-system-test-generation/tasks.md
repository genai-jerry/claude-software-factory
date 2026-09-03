# Tasks: System Test Generation

Companion Console change: `add-system-test-tasks-console` in
`software-factory-view` — build it after sections 1 and 6 land, from the
final label, state and comment names.

## 1. Canon and config

- [ ] 1.1 Add `factory:manual-test`, `factory:test-passed` and
      `factory:test-failed` to `scripts/setup-labels.sh` with colours and
      descriptions; move the count note 25 → 28; verify the script is still
      idempotent against a repo that already has the labels.
- [ ] 1.2 Add `templates/factory-testing.json` (`system_tests`, `mode`, a
      `_comment` that states the `epics: false` behaviour) and a `testers`
      key with its fallback (`implementation`) to
      `templates/factory-approvers.json`; add `testplanner` to
      `templates/factory-models.json` on the planner's chain; verify all
      three parse.
- [ ] 1.3 Write FACTORY.md §4b "System tests": the two artifacts, the Test
      Planner, test sub-issues and their three states, the two comments,
      the fix task, gate GS accounting in both modes, the `epics: false`
      evidence-only rule, and what expedite does not touch. Update §2
      (stage 2a row; "twelve prompts" → thirteen, also in §10 and README),
      §2a (trigger rows: Test Passed / Test Failed, Release → Dispatcher
      chain, testplanner in the G1 chain row), §2b (`testers` row), §3
      (three state rows; "five labels are not states" unchanged), §4 (GS
      wording), §5 (the `factory` schema), §9 (setup step), §10 (footprint
      row); verify every scenario in the four delta specs has a home.
- [ ] 1.4 Ship `templates/openspec/schemas/factory/` — `schema.yaml` forked
      from `spec-driven` with `test-plan` (requires specs, tasks) and
      `test-data` (requires test-plan) appended, plus
      `templates/test-plan.md` and `templates/test-data.md`; verify
      `openspec schema validate factory` passes when the directory is copied
      into a scratch repo, and `openspec status` lists both artifacts.
- [ ] 1.5 Update `docs/setup-guide.md` (config table row, optional schema
      step, `testers` note) and `wiki/Factory-Pipeline-States.md` (the test
      states beside `factory:on-epic`, the Test Planner in the G1 chain);
      verify the wiki diagram renders.

## 2. The Test Planner role

- [ ] 2.1 Write `commands/testplanner.md`: input (`factory:planned` epic),
      the home-branch and change-folder resolution copied from
      `planner.md`, reads (`proposal.md`, `specs/`, `tasks.md`, profile
      `qa_notes` / `deploy`), the two artifacts in the `test-artifacts`
      format, `Depends on:` derived from the Planner's task → scenario
      mapping, `openspec instructions test-plan` when the repo has adopted
      the schema else the shipped templates, commit on
      `factory/<epic>-design`, one `test(<epic>)` sub-issue per case with
      `Covers:` and `Blocked by` lines and `Part of` when cross-repo, the
      checklist comment on the epic, the idempotent re-run rule (never
      renumber; withdraw), and guardrails (black-box, synthetic data only,
      never a `factory:*` label on a test sub-issue, leave the epic at
      `factory:planned`); verify against every `test-planner` scenario.
- [ ] 2.2 Update `commands/planner.md` (state that test sub-issues are not
      in the ~10 cap and that the task → scenario mapping is what the Test
      Planner reads), `commands/architect.md` (read `system-tests/` when
      present; the G2 hand-off names the plan's case and data-set counts;
      design for the plan's data and environment needs), and
      `commands/reviewer.md` (a real value under `system-tests/` is a
      blocking finding on a design PR); verify no prompt applies a test
      state.
- [ ] 2.3 Update `commands/dispatch.md`: `test(<epic>)` children as a second
      kind; dependency "done" = the assembled state (`factory:on-epic`, or
      `factory:in-staging` without an epic branch); release to
      `factory:manual-test` with the testers assigned and the environment
      named; `factory:test-failed` → `factory:manual-test` when the fix is
      assembled; the completeness check (step 4) gains the `mode: gate`
      clause and posts the test matrix in the GS notice; ignore `test(`
      children when the policy is off; verify against every
      `manual-test-tasks` Dispatcher scenario.
- [ ] 2.4 Update `commands/release.md`: phase 1 step 5 gains the same
      completeness clause and the "assembled, waiting on N tests" report;
      phase 1b/2 list the test matrix in promotion PR bodies and the
      merge-list comment, flagging unverified cases; `commands/ops.md` cites
      the matrix in the verification summary and archives `system-tests/`
      with the change; `commands/qa.md` notes `Execution: automatable` cases
      as hints only; verify the release prompt matches the gate scenarios in
      both modes.

## 3. The decision table (both routers + fixtures)

- [ ] 3.1 Add `isTestTitle` (`^test\(\d+\)`) beside `isTaskTitle` in both
      routers and a `testing` config loader (`.github/factory-testing.json`,
      absent/invalid ⇒ off) with a `testing` key in the fixture schema and
      `SCHEMA.md`; verify existing fixtures pass unchanged.
- [ ] 3.2 Implement the `issue_comment` branch for `Test Passed` (authorise
      against `testers` → `implementation` → anyone; flip to
      `factory:test-passed`, close, receipt; then route `dispatch` to the
      epic when it is `factory:design-approved`) and `Test Failed` (open the
      `task(<epic>): fix ST-<n> — <title>` sub-issue at `factory:ready` with
      the start notice, append `Blocked by`, flip to `factory:test-failed`;
      refuse a second failure); the wrong-state and not-enabled replies;
      in both engines.
- [ ] 3.3 Implement the `labeled` handling: `factory:manual-test` assigns
      and @-mentions the testers (like `factory:ready` does the
      implementation approvers); a code state hand-applied to a `test(`
      sub-issue is reverted with a comment; `factory:expedite` applied to an
      epic whose open children are all test sub-issues says what it waits
      on and starts nothing; in both engines.
- [ ] 3.4 Add conformance fixtures for every routing scenario in the
      `manual-test-tasks` and `test-planner` specs (pass authorised /
      unauthorised / wrong state / not enabled, fail files the fix, second
      fail refused, last pass routes dispatch, pass with tasks still open
      routes nothing, manual-test notifies testers with fallback, code state
      on a test reverted, expedite on runnable tests, policy absent and
      invalid) and run them against both routers; verify
      `scripts/test-router.js` and `test_conformance.py` stay green.

## 4. Chaining

- [ ] 4.1 Actions: extend `architect-chain` into a two-hop chain — after
      the Planner reaches `factory:planned`, run `testplanner` when the
      policy enables it, then `architect` when the epic is still
      `factory:planned` — sharing the checkout ladder; add a
      `dispatch-chain` job after a `release` run that lands anything
      (epic still `factory:design-approved`); verify with a repo without
      the policy file that the G1 chain is byte-for-byte today's.
- [ ] 4.2 Orchestrator: add the `testplanner` hop and the `release →
      dispatch` hop to `chain_node`, with the policy read from the repo
      config; verify a full epic (spec-ready → tests released → last pass →
      epic-ready) completes in the devapp under `mode: gate`.
- [ ] 4.3 Add `testplanner` to every place the role set is enumerated
      (workflow `role` validation and model resolution, `role_runner`, the
      plugin's description and the harness); verify a manual
      `workflow_dispatch` of `testplanner` on a `factory:planned` epic runs.

## 5. Trace contract

- [ ] 5.1 Add `factory:manual-test`, `factory:test-failed` and
      `factory:test-passed` entries to `handbook/next-step.json`
      (`{approvers}` from `testers` → `implementation`), and a `tested`
      wording variant for `factory:design-approved` and `factory:on-epic`
      selected when the policy enables system tests; update both renderers
      and `GATE_OF_STATE` / `GATE_FALLBACK`; verify `test_next_step.py`
      renders identical text through both engines for the new states.

## 6. Console

- [ ] 6.1 Implement `add-system-test-tasks-console` in
      `software-factory-view` (label catalogue, `test(` task kind, tester
      attention items, Pass/Fail actions, plan and data in the artifact
      reader, test matrix on the GS panel, epic status wording); tracked in
      that repo's change folder.

## 7. Verification

- [ ] 7.1 Pilot on one repo through the test harness
      (`templates/workflows/factory-test.yml`): an epic with three
      scenarios runs intake → G1 → Planner → Test Planner → Architect → G2;
      the design PR carries all four documents; after dispatch,
      implementation and assembly the test sub-issues are released; one
      `Test Failed` files a fix that lands and re-releases the case; the
      last `Test Passed` flips `factory:epic-ready` with the matrix; record
      the trace as a wiki page beside `Run-Trace-Issue-16.md`.
