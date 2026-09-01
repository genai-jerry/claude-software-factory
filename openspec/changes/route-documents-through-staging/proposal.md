# Route Documents Through Staging

## Why

The factory's central promise is that **nothing reaches the default branch
without being proved on the integration branch first** (§6a), enforced three
ways (§8a). Under `epics: false` there is one exception, and it is not small:
spec PRs, plan+design PRs and profile PRs base on the **default branch** and
merge straight there at gate G1/G2 approval.

§6 gives the reason plainly: *every later stage of a no-epic-branch epic
clones the default branch*, so an approved spec parked on the integration
branch would be invisible to the planner, the architect and every
implementer until the next release promoted it. The exception exists to serve
the read path, not because documents belong on the default branch.

That reasoning is circular, and it is now costing something real. With
`factory:expedite` (§4a) gates G1 and G2 can approve themselves, so on
`epics: false` an epic's documents reach the default branch with **no human
click at any point** — the marker is the only approval. The carve-out that
was a quiet asymmetry becomes a way for content to arrive on the production
branch unattended.

Fix the read path and the exception disappears: send documents to the
integration branch, and have the stages that read them check out the
integration branch. `epics: true` already works exactly this way against the
epic branch — documents merge to it *and* stages read from it (§6b). This
change makes `epics: false` the same shape, one branch lower.

## What Changes

- **Document PRs under `epics: false` base on the integration branch**, not
  the default branch: `factory/<epic>-spec` and `factory/<epic>-design` are
  cut from it and merge back into it at gates G1 and G2.
- **Profile PRs base on the integration branch too.** `.factory/profile.json`
  is read by every role at step 0 from the checkout it already makes; a
  profile that lands only on the default branch would be invisible to roles
  reading the integration branch, and nothing merges the default branch into
  integration on a schedule. It reaches the default branch with everything
  else, at promotion.
- **Stages read from the integration branch under `epics: false`.** Planner,
  architect, dispatch, implementer, reviewer, qa, release and ops resolve
  their checkout as: the epic branch when the epic has one, else the
  integration branch, else (no integration branch — `required: false`) the
  default branch. This is the change that makes the above safe, and it is
  the same rule `epics: true` already follows one level up.
- **Gate approval retargets in both directions.** The shared `approve_gate`
  helper already retargets a default-branch-based document PR onto the epic
  branch when `epics: true`. It now also retargets one onto the **integration
  branch** when `epics: false`, so in-flight epics adopt the new routing at
  their next gate rather than being stranded.
- **`factory:expedite` no longer merges anything to the default branch.** The
  §4a note that documented that consequence goes, because the consequence
  goes with it.
- **Unchanged:** `epics: true` routing in every respect; implementation PRs
  (already integration-based); gate G3 as the only path to the default
  branch; the fast lane; and — deliberately — the §8a branch guard's
  documents-only allowance, which stays as a legacy tolerance while epics
  that started on the old routing finish. It is now a tolerance rather than a
  description of normal behaviour.

## Capabilities

### New Capabilities

- _(none)_

### Modified Capabilities

- `branching/artifact-routing`: document and profile PR bases under
  `epics: false`; the stage checkout rule; gate retargeting toward the
  integration branch.

## Impact

- **BREAKING for `epics: false` estates**, in the same shape as the epic-branch
  flip was: an epic whose documents already merged to the default branch
  finishes on the old routing, and one whose document PRs are still open is
  retargeted at its next gate approval. Nothing is stranded either way,
  because the read path resolves per run rather than per epic.
- Repos on `epics: true` (the shipped template) see **no change at all**.
- Repos with `required: false` — no integration branch — keep default-branch
  routing exactly as today; there is nowhere else to put documents.
- One new read for both routers: `.factory/profile.json`, needed to resolve
  the integration branch's *name* when a repo overrides it (§6a).
