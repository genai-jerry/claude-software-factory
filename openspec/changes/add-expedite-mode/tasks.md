# Tasks: Expedite Mode

Companion Console change: `add-expedite-mode-console` in
`software-factory-view` — build it after section 6 lands, from the same
label/state names.

## 1. Canon and config

- [x] 1.1 Add `factory:expedite` (marker) and `factory:epic-ready` (state)
      to `scripts/setup-labels.sh` with colors/descriptions; verify the
      script's label count and idempotence note move 23 → 25.
- [x] 1.2 Add `expedite` and `staging` keys to
      `templates/factory-approvers.json` and document their fallbacks
      (`staging` → `release` list; `expedite` → owner/member/collaborator)
      in FACTORY.md §2b; verify the JSON parses.
- [x] 1.3 Write FACTORY.md's expedite section (a §4a beside the gates):
      what the marker waives, what it never touches (G0, GS, G3), scope and
      refusals, inheritance by tasks, removal, engine notes including the
      Actions PAT requirement; update §1's "humans holding the gates"
      framing to name the two ship gates.
- [x] 1.4 Update FACTORY.md §3 (state table: `factory:epic-ready` row
      between `factory:on-epic` and `factory:in-staging`; `factory:expedite`
      marker row; "four labels are not states" → five), §4 (gate GS entry;
      the integration merge is no longer "deliberately not a gate"), §2a
      (trigger rows: marker applied/removed, `Approved` at
      `factory:epic-ready`, role-completion chaining), §2b (gate table
      rows), and §6b ("Leaving the epic branch" now waits on GS); verify
      every scenario in the three delta specs has a home in the tables.

## 2. The decision table (both routers + fixtures)

- [x] 2.1 Refactor the gate merge-and-flip routine (find gate PR, §6b
      retarget, squash-merge, label flip, follow-up role) out of the
      comment-approval branch into a shared helper in each engine
      (`router.py` and the workflow `route` script); verify existing
      conformance fixtures still pass unchanged before adding behavior.
- [x] 2.2 Implement the `labeled`/`unlabeled` handling for
      `factory:expedite`: authorization against the `expedite` list with
      revert + comment (App writes exempt), refusal on trackers/profile/
      fast-track issues, dormant pre-spec, immediate action on the current
      state via the auto-advance map, and the removal notice; in both
      engines.
- [x] 2.3 Implement expedite resolution for task events (epic via task
      title + `Part of` marker, cross-repo via `port_for`/PAT with the
      comment fallback) and the auto-advance decisions for task states
      (`ready` → implementer, `in-review` → reviewer, `in-test` → qa,
      `ready-to-ship` → release under `epics: true` only); in both engines.
- [x] 2.4 Implement gate GS: `Approved` comment at `factory:epic-ready`
      authorized against `staging` (fallback `release`) starting Release
      phase 2; approver assign + @-mention on entering the state; the
      unauthorized refusal; keep `factory:in-staging`'s G3-is-merge-only
      reply; in both engines.
- [x] 2.5 Add conformance fixtures for every scenario in the three delta
      specs (authorized/unauthorized/refused application, dormant pre-spec,
      G1/G2 auto-approval, each task-state hop, rework cap, blocked pause +
      resume, marker removal mid-chain, epics:false stop at ready-to-ship,
      epic-ready flip, GS approval/refusal, demotion re-arm) and run them
      against both routers; update `scripts/test-router.js` as needed.

## 3. Actions engine chaining

- [x] 3.1 Replace `architect-chain` with a generalized `expedite-chain` job:
      after `agent`/`release-chain`, read the resulting state of each issue
      the run changed, consult the map, and redispatch the pipeline
      (`workflow_dispatch`, role + issue, one per follow-up) over
      `FACTORY_CROSS_REPO_TOKEN`; keep planner→architect chaining in-run and
      byte-for-byte equivalent for non-expedited epics; verify with a
      non-expedited epic run that architect chaining is unchanged.
- [x] 3.2 Implement the missing-PAT degradation: say-once comment naming the
      token requirement and the manual control, job ends green; verify the
      say-once marker prevents repeats.
- [x] 3.3 Guard against dispatch storms: only redispatch for issues whose
      state this run changed, and rely on the `factory:in-progress` guard
      for double starts; verify a redispatched run that finds its state
      already advanced exits without dispatching.

## 4. Orchestrator engine chaining

- [x] 4.1 Extend `chain_node` with the auto-advance map (task hops, G1/G2
      auto-approval via the 2.1 helper, dispatch fan-out of ready tasks via
      `Send`), and flip `factory:epic-ready` when a chained release/dispatch
      result completes the epic; verify against the new fixtures.
- [x] 4.2 Replace the fixed `MAX_ROUNDS = 4` with a per-execution budget
      derived from the epic's task count and rework cap; verify a full
      expedited epic (spec-ready → epic-ready) completes in one graph
      execution in the devapp.

## 5. Role prompts

- [x] 5.1 Update `commands/release.md`: phase 1 flips the epic to
      `factory:epic-ready` when it lands the last task (no self-directed
      phase 2); phase 2 runs only from a gate-GS start and covers both
      `epics` policies; demotion path re-arms GS; verify the prompt matches
      the staging-gate spec scenarios.
- [x] 5.2 Update `commands/dispatch.md` (flip `factory:epic-ready` when a
      re-dispatch finds the epic complete; note that expedited ready tasks
      are started by the engine, not by approvers) and touch
      `reviewer.md`/`qa.md` only where they name "a human starts the next
      role"; verify no role prompt ever applies or removes
      `factory:expedite`.

## 6. Trace contract

- [x] 6.1 Add the `factory:epic-ready` entry to `handbook/next-step.json`
      (gate GS wording, `{approvers}` from `staging`→`release` fallback) and
      an `expedited` wording variant for `factory:spec-ready`,
      `factory:design-ready`, `factory:ready`, `factory:in-review`,
      `factory:in-test` and `factory:ready-to-ship`; update both renderers
      (`scripts/say_next_step.py`, `factory_orchestrator/next_step.py`) to
      select the variant by marker presence; verify both render identical
      text for the same issue.

## 7. Console

- [x] 7.1 Implement `add-expedite-mode-console` in `software-factory-view`
      (expedite toggle + confirm, badges, attention-queue suppression, GS
      gate panel, epic-ready phase); tracked in that repo's change folder.

## Deviations from this plan, and why

Two things were planned one way and built another. Both are recorded here
rather than quietly absorbed, because the plan is the artifact a reviewer
reads first.

- **3.1 said "replace `architect-chain`"; it was kept and `expedite-chain`
  added beside it.** Replacing the in-run planner→architect chain with a
  re-dispatch would have made *every* epic's architect step depend on
  `FACTORY_CROSS_REPO_TOKEN` — the workflow token cannot start workflow runs.
  Single-repo estates without a PAT would have silently lost their architect,
  which is a regression the plan did not intend. `architect-chain` therefore
  runs unchanged and `expedite-chain` handles only the expedite follow-ups.
  `scripts/test-router.js` scenario 22 asserts both jobs still exist.

- **4.2 said "a budget derived from the epic's task count"; it is a
  constant (`EXPEDITE_MAX_ROUNDS = 32`).** The graph's `fan` `Send`s every
  pending item in one round, so N tasks sitting at the same stage cost one
  round, not N. What actually scales is the length of a single task's
  worst-case walk (four role runs plus two capped rework rounds) behind the
  gate/plan prologue — which does not depend on how many siblings it has. A
  per-task multiplier would have been a bigger number meaning the same thing.
