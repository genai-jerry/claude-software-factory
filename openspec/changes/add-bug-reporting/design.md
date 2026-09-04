# Design: bug reporting

## The shape of the decision

A bug is not a new kind of work. It is a **record** (what a tester saw) plus
a **task** (the change that repairs it). The factory already knows how to run
tasks; what it lacked was the record, and a rule for counting it.

So the design adds one artifact — a `bug(<epic>)` sub-issue — and reuses
everything else:

| Need | Reused from |
|---|---|
| Where the work happens | `task(<epic>)` at `factory:ready` (§2, §6b) |
| How the report waits for its fix | the `Blocked by #<n>` marker (§7), read by the Dispatcher exactly as a failed case's is (§4b) |
| Who confirms the repair | the `testers` list and the two verdict comments (§4b, §2b) |
| Where the epic is held | gate GS's completeness rule (§4b) |
| How the policy is turned on | `.github/factory-testing.json` (§4b) |

### Why a bug is not a failed case

`Test Failed` on a `test(<epic>)` case says "this case's expected result did
not happen". That statement is only true about a case, and a case only exists
where a plan predicted the path. Overloading it for anything a tester finds
would (a) file fixes titled after cases they have nothing to do with, (b)
park a case that was never run, and (c) make the plan's traceability table
lie. A bug is its own record precisely so the plan stays honest.

The two remain connected: `Bug` is accepted **on** a case's thread, because
that is where a tester usually is when they find something the case did not
predict, and the report then carries `Seen on: #<case>`.

### Why the fix is a separate issue and not the bug itself

The report is the tester's, and it stays theirs: their words, their evidence,
their thread, open until somebody has re-run it. The fix is the factory's —
it takes a code state, a branch, a PR, a review and a QA run. Putting both on
one issue means either an implementer runs on the tester's report (a code
state on a record) or the record closes when the code merges (before anybody
has confirmed anything). Splitting them is what makes the re-test possible at
all.

Both engines therefore refuse a code state applied to a `bug(` issue by hand
and say where the work actually is — the same guard §4b put on cases.

### Why the control reads past its first line

Every other factory control is a strict whole-body match, and deliberately:
"Approved, but…" must not be an approval. `Bug` is the exception because the
report *is* the payload. A strict match would mean the tester's observation
arrives in a second comment that nothing reads, and the fix task quotes an
empty string — which is exactly what the §4b fix task does today with the
body of a `Test Failed`.

The strictness moves to the first line instead: `Bug`, `Bug: <title>`,
`Bug — <title>`. "Bug fix pushed" is a comment, because the first line has
to *end* after the title separator or the word itself. A bare `Bug` with
nothing under it is refused with the shape of a good report.

### Why acceptance is bounded by the epic's state

Bugs are accepted at `factory:design-approved`, `factory:epic-ready` and
`factory:in-staging` — from the first task landing through the staging
window.

- **Earlier**, nothing has been built, so there is nothing to be wrong. What
  the reporter has is a requirement, and requirements enter through intake.
  Accepting one as a bug would file a fix task for behaviour that does not
  exist and attach it to a plan that has not been approved.
- **Later** (shipped, closed, `factory:deployed`), the change has left the
  factory. There is no epic branch to fix into and no gate to hold; that is a
  new issue, or `factory:incident` (§8).

### Why the gate refuses rather than the state reverting

An epic can be at `factory:epic-ready` when a bug is raised — that is the
*normal* case, because that is when a tester is most likely to be exercising
it. §4b already settled the principle for late test plans: **the factory
never moves an epic backwards.** Revoking `factory:epic-ready` would erase
the Release Manager's own verdict that the epic is assembled and green, which
the bug does not contradict.

So the hold lands at the moment somebody asks to release: `Approved` at GS is
refused while a bug is open, naming each bug and its fix. The Dispatcher's
completeness rule covers the other direction — an epic still assembling never
reaches `factory:epic-ready` with a bug open. Together they mean a bug is
never lost, whichever side of the flip it arrives on.

The refusal names the two ways out: close the report (it was not a defect),
or set `mode: advisory`, which turns every hold in §4b and §4c into evidence.

### Why the same two verdict words

A re-test is a test. Adding `Fixed` / `Not Fixed` would give testers four
words for two decisions, and the Console two verdict widgets where one does.
`Test Passed` on a bug at `factory:bug-retest` closes it; the same authority
(`testers`, falling back to `implementation`) owns both, because both are
"this behaviour is now correct".

`Test Failed` stays open to any collaborator, for the same reason §4b gives:
a failure only adds work. It files another fix and returns the report to
`factory:bug-open` — the **same** report, not a new one, so a defect that
takes three rounds has one thread and one history.

## Engine parity

Both engines carry the routing, as §2e requires, with the shared conformance
fixtures as the contract:

- `_bug_control` / `bugControl` — the first-line control and its report.
- `bug_epic_from_body` / `bugEpicFromBody` — the epic a filed report names,
  in the issue form's `### Epic` shape or a hand-written `Epic: #<n>`.
- `raise_bug` / `raiseBug` — one path for both entry points, so a report
  raised by comment and one adopted from a filed issue are the same object.
- `open_bugs` + `bugs_hold_gs` / `openBugs` + `bugsHoldGS` — the gate hold.

Nineteen fixtures pin the decisions, including the two that are easy to get
wrong: an open bug holding GS under `gate`, and the same world **not** holding
it under `advisory`.

## Rejected alternatives

- **Retitling the tester's issue into a `task(...)` and running an
  implementer on it.** One issue, no re-test, and the tester's report becomes
  a work item that closes when the code merges. The confirmation step is the
  point of the feature.
- **A `factory:bug` fast lane** (implement straight from the report, §5).
  The fast lane bases its PR on the integration branch and has no epic — it
  would put the fix on staging *ahead* of the epic that needs it, and outside
  the epic's own verification.
- **Gating G3 on open bugs.** §4b already refused this for cases: G3 is a
  human's merge click, and withholding a merge list the factory was asked to
  post is worse than posting it with the defect named at the top.
- **A separate `bug_approvers` list.** The people who find bugs are the people
  who run the cases. `testers` already means that, and already falls back.
