# Tasks: bug reporting

Companion Console change: `add-bug-reporting-console` in
`software-factory-view` — the epic's Tests tab grows a Bugs section, a
**Report a bug** control and the re-test verdict.

## 1. Canon and config

- [x] 1.1 Add `factory:bug`, `factory:bug-open`, `factory:bug-retest` and
      `factory:bug-verified` to `scripts/setup-labels.sh` with colours and
      descriptions; move the count note 28 → 32; the script stays idempotent
      against a repo that already has them.
- [x] 1.2 Add `bug_reports` to `templates/factory-testing.json` with a
      `_comment` that states the follows-`system_tests` default and both
      overrides.
- [x] 1.3 Add `templates/ISSUE_TEMPLATE/factory-bug.yml` — epic, what
      happened, steps, expected, optional related case — labelled
      `factory:bug`, and say in its own preamble what it is *not* for
      (released behaviour, a failed case).
- [x] 1.4 Write FACTORY.md §4c: the report, the two entry points, the fix
      task, the three states, re-test and confirmation, gate GS in both
      modes, and what expedite does not touch. Update §2a (five trigger
      rows), §2b (the `testers` row), §3 (six markers, four label rows),
      §4b (the cross-reference from a case verdict) and §9 (the template,
      the label count, the policy key).
- [x] 1.5 Add the three states to `handbook/next-step.json`, and
      `factory:bug-retest` → `testers` to both renderers'
      `GATE_OF_STATE`; `factory:bug` joins the kind markers that are never a
      state in both.

## 2. Routing, both engines

- [x] 2.1 Constants, policy (`bug_reports` following `system_tests`), title
      and control helpers, and the kind marker excluded from state
      derivation — `router.py` and the workflow's `route` script.
- [x] 2.2 The `Bug` comment control: epic resolution from the epic itself or
      any of its children, the refusal ladder (policy, access, kind,
      cross-repo, no epic, shipped, wrong state, no report), and the raise.
- [x] 2.3 `raise_bug` / `raiseBug` — one path for both entry points; the fix
      task, the `Blocked by` marker, and the notices on the report, the epic
      and the thread the control was used on.
- [x] 2.4 `adopt_bug` / `adoptBug` on `issues.opened` and `issues.labeled`
      with `factory:bug`, keeping the filed body, with the author-association
      rule for the filed path and the App-write exemption for the label one.
- [x] 2.5 The two verdicts on a bug at `factory:bug-retest`, the re-dispatch
      on confirmation, and the "no effect" explanations for a verdict aimed
      at a bug in any other state.
- [x] 2.6 The gate GS hold: `open_bugs`, `bugs_hold_gs`, the refusal body,
      and the `Approved` branch that reads them.
- [x] 2.7 The code-state revert guard for `bug(` issues, the
      `factory:bug-retest` tester notification, and the re-dispatch when a
      bug closes.
- [x] 2.8 `update_issue_title` on the port, the client and the test fakes —
      adoption is the one route that renames an issue.

## 3. Conformance

- [x] 3.1 `authorAssociation` on fixture issues and `expect.titles` in
      `fixture.schema.json`, both harnesses and `SCHEMA.md`.
- [x] 3.2 Nineteen fixtures: raising by comment and by label, every refusal,
      both verdicts, the gate held under `gate` and **not** held under
      `advisory`, the code-state revert, and the tester notification. Both
      engines run them green.

## 4. Roles

- [x] 4.1 `dispatch.md`: step 0 reads `bug_reports`; step 2b releases a bug
      to `factory:bug-retest` when its fix is assembled; step 4's
      completeness rule gains "no bug open" in `gate` mode, and the "never
      move an epic backwards" rule covers a late bug.
- [x] 4.2 `release.md`: bugs in the completeness rule, the assembly report,
      the gate GS notice and the promotion PR's evidence.
- [x] 4.3 `ops.md`: bugs in the closure summary, and what an open bug on a
      shipped epic means. `planner.md`: bug reports and their fix tasks never
      enter `tasks.md`.

## 5. Console (software-factory-view)

- [ ] 5.1 The four labels, the three states and the `bug` issue kind in
      `packages/core` — label table, state derivation, phases, state
      sentences and the next-step wording.
- [ ] 5.2 The API: bug rows in the epic workspace payload, `POST
      /api/epics/:id/bugs` posting the `Bug` comment as the acting user, and
      the re-test verdict on a bug.
- [ ] 5.3 The Tests tab: a Bugs section grouped by state, a **Report a bug**
      form, and the Pass/Fail control on a bug at re-test.
- [ ] 5.4 Tests for the new core functions, the endpoints and the tab.
