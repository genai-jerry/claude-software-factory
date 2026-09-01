# Design: Route Documents Through Staging

## Context

Three facts decide this change:

1. **§6's exception is a read-path workaround.** Documents go to the default
   branch under `epics: false` "because every later stage clones the default
   branch". Move the read, and the write follows.
2. **`epics: true` already proves the shape.** Documents merge to the epic
   branch *and* every post-intake stage checks it out (§6b). Nothing about
   that is specific to epic branches — it is "documents live where the stages
   read".
3. **The integration branch is agent-writable and the default branch is not**
   (§8a). Moving documents down one branch moves them from the one branch
   agents may not write to, onto one they may.

Where the current behaviour is expressed:

- `commands/*.md` — intake, planner and architect name their branch bases
  inline; implementer, fasttrack, reviewer, qa and release resolve the
  integration branch in a shared "step 0a"; dispatch and ops name the branch
  they read the change folder from.
- `.github/workflows/factory-pipeline.yml` — one step per agent job resolves
  the checkout for epic-scoped roles (planner, architect, dispatch, release,
  ops); `epics: false` falls through to the default checkout.
- Both routers' `approve_gate` — retargets a document PR base at the gate.
- `hooks/protect-branches.py`, `factory-branch-guard.yml` — unchanged; the
  integration branch was always writable.

## Goals / Non-Goals

**Goals**

- One rule for where an epic's documents live, with the branch chosen by
  policy rather than by which artifact it is.
- Close the `epics: false` path by which expedite puts content on the default
  branch unattended.
- Adopt in-flight epics without stranding any, in either direction.

**Non-Goals**

- No change to `epics: true`.
- No change to gate G3, the fast lane, or the protected-branch enforcement.
- Not tightening the branch guard's documents-only allowance (a separate
  decision, deliberately deferred while old-routing epics finish).

## Decisions

### D1 — One resolution order, with reads allowed to fall through

Every role resolves its branch on the same ladder:

1. the **epic branch** `factory/epic-<n>`, when `epics: true` and it exists;
2. else the **integration branch** (§6a: profile `branches.staging` when it
   is a non-null string, else the policy's `staging`, else `"staging"`);
3. else the **default branch** — reached when the policy sets
   `required: false` and the repo has no integration branch.

Writing uses the ladder as-is: a new document PR bases on the first rung that
applies. **Reading takes the first rung that actually carries the epic's
change folder.** In steady state those are the same branch. They differ for
exactly one population, and it is the one that matters during the flip: an
`epics: false` epic whose documents already merged to the default branch
under the old routing has its folder on rung 3 while policy points at rung 2.
A fixed rung-2 read would strand it — the planner, architect and every
implementer would check out the integration branch and find no change folder
at all.

So the read is "the first of these branches that has
`openspec/changes/<epic>-*/`", not "the branch policy names". That is also
truer to the engine contract than a computed answer: artifacts are
authoritative, and the folder's location is an observable fact.

Expressing this once, rather than per role, is the point. The prompts get the
same ladder; the workflow's checkout step gets it; both routers get the write
half in `approve_gate`.

### D2 — Profile PRs follow the same ladder, minus the epic

`.factory/profile.json` has no epic, so its ladder is steps 2–3: the
integration branch, else the default branch. The alternative — leaving it on
the default branch and having roles read it from there — was rejected: a role
makes **one** checkout, and a two-source read (change folder from here, profile
from there) is a new failure mode in every role, to save a delay that only
matters between releases.

The cost is real and worth stating: a profile fix now reaches the default
branch at the next promotion rather than immediately. It reaches *the agents*
immediately, which is what a profile is for.

### D3 — Retarget at the gate, in both directions

`approve_gate` already moves a default-branch-based document PR onto the epic
branch when `epics: true`, and back when `epics: false`. That second arm now
targets the **integration branch** instead of the default branch, and a
default-branch-based PR under `epics: false` is retargeted onto integration
too. A retarget keeps the PR, its reviews and its head branch, so an epic
mid-flight adopts the new routing at whichever gate it reaches next.

An epic whose documents have *already merged* to the default branch is not
rewritten: there is no PR left to retarget and rewriting history to move them
is never worth it. It finishes on the old routing, and D1's fall-through read
is what makes that safe — its roles look for the change folder, find it on
the default branch, and carry on.

### D4 — Both routers need the profile

The integration branch's *name* can be overridden per repo by
`.factory/profile.json` (§6a). Until now only the roles resolved it, and the
routers never needed it. `approve_gate` does now, so `RepoConfig` gains a
`profile` field and a `staging_branch` property implementing the §6a ladder.
It is one more file read on the gate path, cached in the config object the
router already builds once per event.

Where the profile is missing or unparseable, the policy's name applies — the
same tolerance as everywhere else. Where `required: false`, `staging_branch`
returns None and the gate keeps default-branch routing.

### D5 — What this does to expedite

§4a's "One thing it does merge" paragraph, added with the expedite change,
described exactly this exception. It is deleted rather than reworded: with
documents on the integration branch, **no auto-advanced action reaches the
default branch under either policy**, which is what §4a claimed everywhere
else. The change makes the simpler sentence true.

## Risks / Trade-offs

- **A longer-lived integration branch holds more.** Documents now accumulate
  there between releases alongside code. §6a's warning already applies —
  promote often — and documents-only content does not deploy.
- **A profile fix waits for promotion to reach the default branch.** Accepted
  per D2; the agents see it at once.
- **Mixed-routing estates during the flip.** Handled by D3 plus D1's
  fall-through read: an epic reads whichever branch actually carries its
  folder, so old and new epics coexist without either being stranded. This is
  the case the change is most likely to get wrong, so the fixtures pin both
  populations and the prompts state the fall-through explicitly rather than
  leaving it to be inferred.
- **`required: false` repos are unaffected**, which means the exception this
  change removes still exists for them. That is correct: with no integration
  branch there is no staging step at all, which those repos opted out of.

## Migration

1. Merge this change. Repos on `epics: true` need do nothing.
2. `epics: false` repos: in-flight epics adopt at their next gate approval;
   epics whose documents already merged finish on the old routing.
3. The next profile re-check opens its PR against the integration branch. A
   profile already on the default branch keeps working until then — roles that
   check out integration will not see it, so re-run the Profiler if a repo's
   integration branch predates its profile.
4. The branch guard is unchanged, so no new incidents are opened during the
   flip.
