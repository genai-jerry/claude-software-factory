# Design: Epic Branch Strategy

## Context

See `proposal.md` — Why. The mechanics that this design has to change live in
five places:

- **FACTORY.md §6/§6a** — the canonical routing rules. Today: task and
  fast-track PRs base on the one integration branch (`staging`); document PRs
  base on the default branch *because every later stage clones the default
  branch*; only promotion PRs touch `main`.
- **Role prompts** (`commands/*.md`) — implementer, fasttrack, reviewer, qa
  and release each carry a "step 0a" that resolves the integration branch from
  `.github/factory-branches.json` + the repo profile. Intake, planner and
  architect name their branch bases inline.
- **Pipeline workflow** (`.github/workflows/factory-pipeline.yml`, ~1600
  lines) — creates nothing branch-wise today; squash-merges gate document PRs
  on `Approved`; checks out the caller repo (default ref) for agent runs.
- **Guard** (`hooks/protect-branches.py`) — blocks agent pushes/writes to
  `main`/`master` only; `factory/*` and `staging` are already agent-writable,
  so epic branches need no guard change.
- **software-factory-view** — mirrors the label state machine in
  `packages/core/src/factory.ts` (label catalog, gate map) and
  `phases.ts` (label → phase), and renders it in the board/workspace UI.

Constraint: existing estates have in-flight epics on the legacy routing; the
change must be adoptable without breaking them mid-epic.

## Goals / Non-Goals

**Goals:**

- One branch per epic that accumulates *all* of the epic's artifacts, so a
  single checkout (and optionally a preview deploy) shows the whole epic.
- Epic-level isolation: a red epic never blocks another epic's verification.
- Preserve the two invariants the factory is built on: only promotion PRs
  reach the default branch, and nothing is promoted without staging proof.
- Backward compatibility behind a policy switch; legacy mode stays the
  default for absent policy files.

**Non-Goals:**

- Per-epic *production* releases (release trains still promote via staging).
- Changing fast-track (small fixes keep the direct-to-staging lane).
- Changing OpenSpec commands, gate semantics (G0–G3), or approver lists.
- Automated conflict *resolution* between epics — the design only sequences
  where conflicts surface (on the epic branch) and who fixes them.
- Per-epic preview environments themselves — the design defines the hook
  (profile `deploy` entries), not any provisioning tooling.

## Decisions

### D1. Epic branch is cut from the default branch, not from staging

`factory/epic-<n>` is created from the default branch tip. Cutting from
`staging` would leak every other in-flight/awaiting-release epic into this
epic's test surface, defeating "test each epic separately". The cost —
divergence from staging — is paid exactly once, at the integration PR, where
staging is merged *into* the epic branch and the epic re-verified before the
integration PR merges (spec `branching/epic-promotion`). Freshness against
*released* work is maintained by merging the default branch into live epic
branches after every promotion.

*Alternative considered:* cut from staging — fewer integration conflicts, but
epics stop being independently testable, which is the point of this change.

### D2. Document PRs move to the epic branch; stages check out the epic branch

FACTORY.md's stated reason for routing document PRs to `main` is that later
stages clone the default branch, so a spec parked elsewhere is invisible. The
fix is to move both halves together: gate G1/G2 squash-merges land on the epic
branch, and every post-intake stage for an epic checks out
`factory/epic-<n>`. The change folder therefore lives on the epic branch for
the epic's whole life and reaches `main` with the code, via
staging, in the promotion merge — documents and code travel as one unit.
`paths-ignore` on deploy workflows already keeps docs-only merges from
deploying anything.

*Alternative considered:* keep document PRs on `main` and only add an epic
layer for code. Rejected: it leaves the reported problem (spec PRs targeting
`main`) in place, and splits an epic's truth across two branches.

### D3. Policy switch `epics` in `.github/factory-branches.json`, default off

One new boolean beside `staging`/`required`/`auto_create`:

```json
{ "staging": "staging", "required": true, "auto_create": true, "epics": true }
```

Absent file or absent key ⇒ `false` (legacy). The shipped template sets
`true` so new adopters get epic branches. Like the rest of the file it is an
org decision, identical across the estate; a per-epic or per-repo override is
deliberately not offered — mixed routing inside one epic is unreasonable to
support. Epics are keyed to the policy value at the moment they enter intake
(observable from where their spec PR bases), so flipping the switch never
re-routes an in-flight epic.

### D4. Roles resolve branches through one extended "step 0a"

The existing step-0a prose (read policy file → profile override → fallback) is
extended to also resolve the **epic branch** (`factory/epic-<epic-issue>`
when `epics: true`, else "none") and to name each role's **base**: document
and task PRs base on the epic branch when it exists, else on their legacy
base. This keeps the change mechanical across intake, planner, architect,
implementer, reviewer, qa, release, dispatch and ops, and keeps FACTORY.md §6a
(new §6b) the single normative statement.

### D5. Release Manager gains a phase 0.5; states gain `factory:on-epic`

The release role's phase 1 ("merge task PRs onto integration in dependency
order, verify after each") is retargeted at the epic branch and renamed epic
assembly; a new step opens/merges the one integration PR per repo
(epic → staging) when the epic is complete and green, after merging staging
into the epic branch and re-verifying. Staging verification and G3 promotion
are untouched. The extra observable state between "green on epic branch" and
"on staging" is `factory:on-epic` (see spec `branching/epic-promotion`);
`factory:in-staging` keeps its exact current meaning so gate G3 and the view
app's gate map are unchanged.

*Alternative considered:* reuse `factory:in-staging` for "on epic branch".
Rejected: it would make "verified on the shared integration branch" —
the promise G3 approvers rely on — ambiguous.

### D6. Integration PR merges with a merge commit; revert is the demotion path

The epic → staging integration PR merges with a merge commit (not squash), so
task-level history and `Closes #N` links survive, and so a staging failure can
demote *one epic* by reverting one merge commit. Epic branch history is never
rewritten (same rule staging already has).

### D7. View app tracks the new state additively

`software-factory-view` adds `factory:on-epic` to the label catalog, state
order, and phase map (phase: `shipping`, before `factory:in-staging`), plus
board rendering. No gate is attached to it, so the attention/gate logic is
untouched. Legacy estates simply never emit the label.

## Risks / Trade-offs

- **[Two merge frontiers per epic]** (default→epic refresh, staging→epic at
  integration) mean more merges and more conflict opportunities than the
  single-staging model. → Conflicts surface earlier, on a branch agents may
  write to, with `factory:blocked` + named files; refresh runs only on
  promotion events, not on a timer.
- **[Epic branches rot if an epic stalls]** → Same mitigation the integration
  branch already documents ("promote often") plus the automatic
  default-branch refresh; ops surfaces stale epic branches in its checks.
- **[Workflow complexity]** — factory-pipeline.yml grows branch-creation,
  epic-aware checkout refs and label handling in an already ~1600-line file.
  → Each addition is gated on one policy read; conformance tests
  (`orchestrator/conformance`, `scripts/test-router.js`) cover the routing
  matrix for both policy values.
- **[Staging-first invariant could be accidentally weakened]** — an epic
  branch merging to `main` directly would skip staging. → Guard layer-3
  provenance check extends: a `main` merge whose head is not the integration
  branch (docs-only excepted) is already reported; epic branches add no new
  path to `main`.
- **[Per-epic verification without per-epic environments]** is only CI-level
  proof. → Acceptable: staging verification still happens at integration; the
  profile's `deploy` block is the extension point when an estate can afford
  preview environments.

## Migration Plan

1. Ship the capability fully behind `epics: false` (no estate behavior
   change on upgrade).
2. An adopting org flips `epics: true` in `.github/factory-branches.json`
   estate-wide (one PR per repo, or the setup step for new repos).
3. In-flight epics finish on legacy routing; epics entering intake after the
   flip route through epic branches. No data or label migration is needed —
   `factory:on-epic` only ever appears on new-style epics.
4. Rollback: flip the policy back; new epics revert to legacy routing.
   In-flight epic-branch epics either finish under their original routing
   (roles key off where the spec PR based, per D3) or are re-intaken.

## Open Questions

- Whether the default-branch → epic-branch refresh (D1) should also be
  offered on demand (a comment command) for long-lived epics between
  releases. Deferrable: additive trigger, no spec impact.
- Label color/name bikeshed for `factory:on-epic` in `setup-labels.sh` and
  the view catalog. Deferrable: cosmetic.
