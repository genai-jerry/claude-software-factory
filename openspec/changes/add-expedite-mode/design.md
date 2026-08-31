# Design: Expedite Mode

## Context

The factory's human touchpoints after the spec exists, today:

| Point | State | Control |
|---|---|---|
| Gate G1 | `factory:spec-ready` | Merge spec PR or comment `Approved` |
| Gate G2 | `factory:design-ready` | Merge design PR(s) or comment `Approved` |
| Implementation start | task `factory:ready` | Comment `Approved` per task |
| Review start | task `factory:in-review` | Run workflow / Console button |
| QA start | task `factory:in-test` | Run workflow / Console button |
| Assembly start | task `factory:ready-to-ship` | Run workflow / Console button |
| Epic → staging | epic all-`factory:on-epic` | Human starts Release phase 2 by hand |
| Gate G3 | `factory:in-staging` | Human merges promotion PR(s) in the UI |

Only two of those are decisions the requester wants to keep for a trusted
epic: the staging release and G3. Everything else is a start button.

The mechanics live in four places that must move together:

- **The routing decision table** — implemented twice: the `route` script in
  `.github/workflows/factory-pipeline.yml` and its line-faithful port
  `orchestrator/src/factory_orchestrator/router.py`, pinned by the shared
  fixtures in `orchestrator/conformance/`.
- **In-run chaining** — the Actions `architect-chain` job and the
  orchestrator's `chain` node (`graph.py`) are the only existing
  auto-advance: planner → architect, gated on `factory:planned`.
- **The trace contract** — `handbook/next-step.json`, rendered by
  `scripts/say_next_step.py` and `factory_orchestrator/next_step.py`; every
  run must keep saying, truthfully, who moves the issue next.
- **The Console** — mirrors labels/gates in `packages/core` and renders the
  controls (companion change in software-factory-view).

Constraint: the Actions engine's workflow token cannot emit events that
trigger workflows (GitHub anti-recursion), so "the label flipped, the next
stage fires" does not happen by itself there. The orchestrator, acting as a
GitHub App, does emit real events — but relying on that would fork the two
engines' behavior. Chaining must therefore be explicit in both.

## Goals / Non-Goals

**Goals**

- One switch, applied at any post-spec step, that removes every remaining
  start-button and gate touch up to — but never including — staging.
- Staging and production stay human decisions, now as explicit gates.
- One decision table: both engines, the fixtures, the next-step wording and
  the Console change in lockstep; no expedite-only state machine.
- Reversible and interruptible: remove the label, or `factory:blocked`, and
  the pipeline is exactly the pipeline that exists today.

**Non-Goals**

- No change to the fast lane (`factory:fast-track`) — it already has no gates
  before G3 and stays the right tool for changes too small for ceremony.
- No auto-approval of G0 (release scope), GS or G3, ever.
- No org-wide or repo-wide expedite default: the marker is per-issue. (An
  estate that wants it always-on can apply the label from its own automation;
  the factory does not ship that switch.)
- No new engine, queue, or persistent state outside GitHub labels.

## Decisions

### D1 — A new orthogonal marker, not a reuse of `factory:fast-track`

`factory:expedite` is a marker like `factory:blocked`: it sits alongside the
one state label and no state transition depends on it except the auto-advance
decisions defined here. Reusing `factory:fast-track` was rejected: that label
means "skip the pipeline" (the router refuses it on in-flight issues, its
done-marker logic assumes a single PR, and §5 defines it as the no-ceremony
lane). Overloading it would make one label mean two opposite things — skip
the ceremony vs. run all of it faster.

Naming: "expedite" in every identifier; prose may say "fast-track the
pipeline" when introducing it, but the label, config key and fixture names
never say fast-track.

### D2 — The marker lives on the epic; tasks inherit it

Task sub-issues consult their epic (`task(<n>)` title, `Part of` marker for
the repo — the same resolution the task-closed re-dispatch already does,
including its cross-repo `port_for`/PAT constraint and its "comment rather
than silently stop" fallback). The label is not copied onto tasks: a copy can
drift from the source of truth when a human removes expedite mid-flight.
Routing decisions on a task therefore cost one extra issue read.

### D3 — Authorization at application time, not at each gate

Applying `factory:expedite` pre-approves G1, G2 and every implementation
start, so the application is what gets authorized: a new `expedite` key in
`.github/factory-approvers.json`, empty ⇒ any owner/member/collaborator.
The `labeled` router branch validates the sender exactly as it does for
hand-applied `factory:*-approved` labels — revert + explanatory comment when
unauthorized, exempting the factory's own App writes. The subsequent
automatic gate flips are factory-authored and need no further check (same
principle as the App-write exemption that already exists).

### D4 — The auto-advance map, and where each edge runs

| Trigger observed | Issue | Auto action while expedited |
|---|---|---|
| `factory:expedite` applied | epic | Act on the *current* state immediately per the rows below (an epic parked pre-spec just keeps the marker; intake/G0 are untouched) |
| `factory:spec-ready` reached or current | epic | G1: merge spec PR, flip to `factory:spec-approved`, run Planner (→ Architect, existing chain) |
| `factory:design-ready` reached or current | epic | G2: merge design PR(s), flip to `factory:design-approved`, run Dispatch |
| task reaches `factory:ready` (dispatch, re-dispatch, or reviewer rework) | task | Start Implementer (rework restarts count toward the existing 2-round cap → `factory:blocked`) |
| task reaches `factory:in-review` | task | Run Reviewer |
| task reaches `factory:in-test` | task | Run QA |
| task reaches `factory:ready-to-ship` | task | `epics: true`: run Release phase 1 (→ `factory:on-epic`). `epics: false`: stop — see D5 |
| last task reaches its end state | epic | Flip epic to `factory:epic-ready`, assign + notify `staging` approvers. Auto-advance ends |

The gate-merge logic (find gate PR, retarget per §6b, squash-merge, flip)
already exists in the comment-approval branch of both routers; it is
refactored into a helper both the comment path and the expedite path call,
so the two paths cannot drift.

### D5 — The chain never performs a staging-deploying merge

Under `epics: true`, Release phase 1 merges task PRs onto the *epic branch* —
safe, staging untouched — and the chain runs it. Under `epics: false` the
Release role's first act is merging onto the integration branch, which *is*
the staging deploy, so the chain stops at `factory:ready-to-ship` and the
epic flips to `factory:epic-ready` when every task is there. GS approval then
starts the Release Manager over the whole epic (dependency-ordered merges,
staging verification, promotion PRs) in both modes. One gate, one meaning:
"approving this releases the epic to staging."

### D6 — `factory:epic-ready` and gate GS are universal

Two state machines (expedited vs. not) would double the fixtures, the
next-step wording, the Console phase map and every future maintainer's
mental model. Instead the new state applies to every epic: the Release run
that lands the last task (or, on a task-close re-dispatch, the Dispatcher
finding nothing left to release) flips the epic to `factory:epic-ready`
instead of a human informally starting phase 2. Approver key `staging`,
falling back to the `release` list when absent, is assigned and @-mentioned;
`Approved` on the epic (strict match, like every gate comment) or the
Console's button opens the gate. G3 keeps its "merge click only" rule.
This is the one behavioral break for non-expedited epics and is called out
in the proposal's Impact.

### D7 — Actions engine chains by self-redispatch over the PAT

In-run chaining (the `architect-chain` pattern) cannot express the task
pipeline: dispatch fans out to N tasks, each task then needs up to four
sequential role runs with per-role model resolution and its own timeout
budget, and a matrix cannot be re-derived mid-run. Instead a new
`expedite-chain` job (generalizing `architect-chain`, which it absorbs) runs
after `agent`/`release-chain`, reads the resulting state, consults the map,
and re-dispatches the pipeline (`workflow_dispatch`, role + issue) once per
follow-up issue using `FACTORY_CROSS_REPO_TOKEN`. Each role gets its own
run: real 45-minute timeouts, the existing matrix, the existing
in-progress marker guard against double starts.

Without the PAT the redispatch is impossible (workflow-token events do not
trigger runs), so the job posts one say-once comment on the issue — expedite
needs the PAT on this engine; here is the next manual control — and the
normal handbook next-step still stands. The orchestrator engine needs no
token gymnastics: its `chain` node appends follow-ups as graph work
(`Send`), reusing the release fan-out pattern; `MAX_ROUNDS` becomes a
per-execution budget derived from task count rather than the current
constant 4.

### D8 — The trace contract keeps telling the truth

`handbook/next-step.json` entries gain an optional `expedited` variant per
state; both renderers pick it when the epic carries the marker. Expedited
`factory:in-review` says "the Reviewer starts automatically — nothing to
do"; un-expedited keeps today's wording. New entries: `factory:epic-ready`
(gate GS wording, `{approvers}` from `staging`), and a removal notice when
`factory:expedite` is taken off (normal controls resume from the current
state). The say-once discipline is unchanged.

## Risks / Trade-offs

- **Runaway automation.** Bounded by construction: the map has no cycle
  except reviewer rework, which the existing 2-round cap already terminates
  into `factory:blocked`; every auto-start passes the in-progress guard; the
  chain acts only on states the map names. Fixtures assert the chain stops
  at `factory:epic-ready`, at `factory:blocked`, and on marker removal.
- **PAT dependency on the Actions engine.** Accepted: the PAT is already
  the documented prerequisite for cross-repo estates, and degradation is a
  visible comment, not a silent stall.
- **Redispatch loops.** A redispatched run computes its own follow-ups from
  observed state, so a crashed run loses at most one hop — the next human
  or agent event re-enters the map. A dispatch-storm guard: `expedite-chain`
  redispatches only for issues whose state its own run just changed.
- **Cross-repo expedite lookups** add one API read per task event and fail
  toward "do nothing + comment" without the PAT — the same posture as
  re-dispatch today.
- **GS adds one human touch to non-expedited epics** that previously flowed
  through an informal manual start. It is the same click, now with a
  notification, an approver list and an audit trail.

## Migration

1. Ship labels (`factory:expedite`, `factory:epic-ready`) via
   `scripts/setup-labels.sh`; re-run per repo.
2. Approver keys are optional: absent `staging` falls back to `release`,
   absent `expedite` falls back to owner/member/collaborator.
3. Epics mid-flight: anything short of all-tasks-assembled is unaffected;
   an epic already fully `factory:on-epic` is flipped to
   `factory:epic-ready` by hand once (or by its next dispatch event).
4. Engines: both routers + fixtures move in this change; a repo on either
   engine picks the behavior up at its next event. No state migration.

## Open Questions

- Should `expedite` also gate *who may remove* the label? Current answer:
  no — removing it only restores human gates, which is always safe.
- Should the Scrum Master be allowed to recommend expedite in a release
  plan (as it may recommend fast-track today)? Deferred; nothing in this
  change prevents it later.
