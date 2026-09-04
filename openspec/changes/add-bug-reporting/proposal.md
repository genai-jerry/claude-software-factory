# Add bug reporting (raise defects found in testing as issues, fix them onto the epic)

## Why

§4b gave the factory a place for the testing a person does: a plan, a case
per unit of it, a state, and a verdict. It answers one question — *did this
case do what the plan said it would* — and testing asks a second one the
factory has no answer for: **what else did you find?**

A tester exercising an assembled epic finds behaviour no case predicted. An
error on a path the plan never named. A number wrong in a way no expected
result mentions. Today that find has nowhere to go:

- `Test Failed` needs a case to fail. A defect on a path with no case is not
  a failure of any case, and reporting it as one puts the wrong story in the
  thread and files a fix titled after the wrong thing.
- A plain issue enters **intake**. It becomes a requirement, gets a spec, a
  plan, a design and gates — weeks downstream of the epic it belongs to, and
  by then that epic has shipped. The defect ships with it.
- So the find becomes a spreadsheet row, a Slack message, or an epic of its
  own that lands long after the change that caused it.

The epic is the right place to repair it. While an epic is between its first
merge and its promotion, it has a branch of its own (§6b), a task machinery
that builds onto that branch, and a gate that has not opened yet. A defect
found in that window can be fixed *inside* the change that caused it, before
anybody outside sees it — but only if the factory can be told about it.

## What Changes

- **A third kind of child for an epic.** `bug(<epic>): <title>`, in the
  epic's own repo, beside its `task(<epic>)` and `test(<epic>)` sub-issues.
  It holds the report a tester wrote and nothing else: the work is a separate
  task.
- **Two ways to raise one**, ending in the same sub-issue: comment `Bug` on
  the epic (or on one of its tasks or cases) with the report underneath, or
  file an issue labelled `factory:bug` naming the epic — from
  `.github/ISSUE_TEMPLATE/factory-bug.yml`, or by labelling an issue somebody
  already wrote.
- **The fix is an ordinary task.** `task(<epic>): fix bug #<n> — <title>` at
  `factory:ready`, with `Blocked by #<fix>` on the report. Same start, same
  implementer, reviewer and QA, same assembly onto the epic branch, under
  whatever approvals and expedite the epic already has.
- **Three states on the report**: `factory:bug-open` (the fix is in flight),
  `factory:bug-retest` (the fix is assembled; a tester confirms it) and
  `factory:bug-verified` (confirmed — the report closes). Plus the kind
  marker `factory:bug`, which never reads as a state.
- **The same two verdicts a case takes.** `Test Passed` on a bug at re-test
  closes it; `Test Failed` files another fix and returns it to
  `factory:bug-open`. A re-test is a test, and the `testers` list already
  owns that word.
- **Gate GS accounting.** Under `mode: gate` with an epic branch, an epic is
  complete only when no bug of it is open, and `Approved` at GS is refused
  while one is — because a bug raised *after* an epic reached
  `factory:epic-ready` must hold the gate without sending the epic backwards.
  Under `advisory`, and with no epic branch, bugs are evidence, exactly as
  cases are.
- **One policy key**, on the file §4b already introduced: `bug_reports` in
  `.github/factory-testing.json`, following `system_tests` when absent.

## What does not change

- No new role. No new document. No new branch. A bug is a report and a task,
  and both already have machinery.
- No new gate. GS is the gate bugs are counted at, and G3 stays a human's
  merge click that the factory never withholds.
- Expedite (§4a) is untouched: none of the three bug states is in the
  auto-advance map, so an expedited epic files and fixes a bug on its own and
  then waits for its testers, exactly as it waits for GS.
- A repo without the policy behaves precisely as it did: `Bug` is answered
  with "not enabled here", and nothing else changes.

## Impact

- **Affected repos:** `claude-software-factory` (canon, both engines, role
  prompts, labels, templates, fixtures) and `software-factory-view` (the
  Console projects the new kind and states, and offers raising and
  confirming from the epic's Tests tab).
- **Migration:** none. Existing epics gain the ability the moment the label
  set and the policy key are in place; nothing already in flight changes
  state.
