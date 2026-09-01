# Tasks: Route Documents Through Staging

## 1. Canon

- [x] 1.1 Rewrite FACTORY.md §6 "Where PRs merge" for the new ladder:
      document PRs under `epics: false` base on the integration branch,
      profile PRs likewise, and the `required: false` case keeps
      default-branch routing; delete the paragraph justifying the old
      exception and state the read rule that replaces it. Verify every case
      in the delta spec appears in the tables.
- [x] 1.2 Add the stage-checkout ladder (epic → integration → default, by
      which branch carries the change folder) to §6a, and cross-reference it
      from §6b so both policies read the same way.
- [x] 1.3 Delete §4a's "One thing it does merge" paragraph — expedite no
      longer reaches the default branch under either policy — and check §4a's
      remaining claims still hold. Note in §8a that the branch guard's
      documents-only allowance is now a legacy tolerance, not a description
      of normal routing.

## 2. Role prompts

- [x] 2.1 `intake.md`: resolve the integration branch (the shared step-0a
      ladder) and, under `epics: false`, cut `factory/<n>-spec` from it and
      base the PR on it; keep `required: false` on the default branch.
- [x] 2.2 `planner.md` and `architect.md`: cut `factory/<n>-design` from the
      same branch and base its PR there; read the approved spec via the
      fall-through read.
- [x] 2.3 `dispatch.md`, `implementer.md`, `reviewer.md`, `qa.md`,
      `release.md`, `ops.md`: state the fall-through read explicitly (first
      branch carrying the change folder, epic → integration → default).
      `implementer.md`'s task-branch base is already the integration branch
      and must not change.
- [x] 2.4 `profiler.md`: base the profile PR on the integration branch when
      one exists; say why (its readers check that branch out) and that it
      reaches the default branch at promotion.

## 3. Both routers

- [x] 3.1 Add `.factory/profile.json` to `RepoConfig` and a `staging_branch`
      property implementing the §6a name ladder (profile override → policy →
      `"staging"`, None when `required: false`); in both engines.
- [x] 3.2 Extend `approve_gate`'s retarget: with `epics: false` and an
      integration branch, retarget a default-branch-based (or epic-branch-
      based) document PR onto the integration branch; keep the `epics: true`
      arm unchanged; in both engines.
- [x] 3.3 Conformance fixtures for both populations: a new `epics: false`
      epic retargeted onto integration at G1 and at G2, the same under
      expedite's auto-approval, `required: false` keeping default-branch
      routing, and `epics: true` unchanged. Run against both routers.

## 4. Actions workflow

- [x] 4.1 Extend the agent-job checkout step: after the epic-branch attempt,
      fall through to the integration branch when it carries the epic's
      change folder, then to the default branch; apply to the same
      epic-scoped roles it covers today. Mirror it in the architect-chain
      job's checkout.

## 5. Console

- [x] 5.1 Check whether `software-factory-view` names document PR bases
      anywhere user-visible (gate panel copy, onboarding stub files) and
      update if so; no behavioural change expected.

## Notes from implementation

- **5.1 found one stale line, not a behaviour change.** `apps/worker/src/
  artifacts.ts` documented the profile PR as `factory/profile` → the default
  branch. The code matches on `head.ref` only, so nothing broke; the comment
  now says why the head is the stable half and the base is not. Console
  checks re-run clean (typecheck, build, 409 tests).
- **The epic-branch tests changed expectations, not coverage.** Three cases in
  `orchestrator/tests/test_epic_branches.py` and three JS scenarios asserted
  documents landing on the default branch under `epics: false`. They now
  assert the integration branch, and two cases were added either side of the
  new rule: `required: false` (the one route left to the default branch) and a
  profile that renames the integration branch.
