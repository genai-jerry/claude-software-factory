# Tasks: Epic Branch Strategy

## 1. Policy and canon (FACTORY.md, templates)

- [x] 1.1 Add `"epics": true` to `templates/factory-branches.json` and
      document the key (default `false` when absent) in FACTORY.md's policy
      table; verify the JSON parses and the table lists all four keys.
- [x] 1.2 Write the new FACTORY.md §6b "The epic branch" (naming, cut point,
      agent writability, refresh-on-promotion, deletion at archive) and
      rewrite §6 "Branching and PRs" / "Where PRs merge" for both policy
      values, per the three delta specs; verify every routing case in
      `branching/artifact-routing` appears in the tables.
- [x] 1.3 Update FACTORY.md §2 stage table, §2a trigger table, §3 states
      table (insert `factory:on-epic` between `factory:ready-to-ship` and
      `factory:in-staging`), §7 cross-repo epics, and §10 setup step 6a;
      verify the state diagram/table transitions match
      `branching/epic-promotion`.
- [x] 1.4 Add the `factory:on-epic` label to `scripts/setup-labels.sh`;
      verify the script is idempotent by dry-reading its label list.

## 2. Role prompts (commands/)

- [ ] 2.1 Extend the shared "step 0a" prose to resolve the epic branch
      (policy `epics` → `factory/epic-<epic-issue>` else none) and apply it
      in `implementer.md`, `fasttrack.md` (explicit "fast lane has no epic
      branch" note), `reviewer.md` (wrong-base finding now names the epic
      branch) and `qa.md` (ready-to-ship promises mergeable onto the epic
      branch); verify each file names the correct base for both policy
      values.
- [ ] 2.2 Update `intake.md`: create `factory/epic-<n>` from the default
      branch (no-op if present) before opening the spec PR, and base the spec
      PR on it when `epics: true`; verify the prompt states the legacy base
      for `epics: false`.
- [ ] 2.3 Update `planner.md` and `architect.md`: cut
      `factory/<epic>-design` from the epic branch and base its PR there
      when `epics: true`; read the approved spec from the epic branch;
      verify both prompts drop the "create from the repo's default branch"
      wording under the new policy.
- [ ] 2.4 Update `release.md`: retarget phase 1 at the epic branch (epic
      assembly, `factory:on-epic` labelling), add the integration-PR step
      (merge staging into epic, re-verify, open/merge epic → staging PR with
      a merge commit, flip to `factory:in-staging`), keep G3 promotion
      unchanged, and add the staging-failure demotion path (revert the
      epic's merge commit → back to `factory:on-epic`); verify the prompt's
      failure section matches `branching/epic-promotion` scenarios.
- [ ] 2.5 Update `dispatch.md` and `ops.md`: dispatcher re-runs on task
      close against the epic branch state; ops deletes the epic branch at
      archive and merges the default branch into live epic branches after a
      promotion (conflict ⇒ `factory:blocked` with file list); verify both
      prompts reference §6b.

## 3. Pipeline workflow (.github/workflows/factory-pipeline.yml)

- [ ] 3.1 Add a policy-read helper step (parse `.github/factory-branches.json`
      including `epics`) and epic-branch creation at intake trigger time;
      verify with a workflow-lint run (`actionlint` or push to a test repo)
      and that creation is a no-op when the branch exists.
- [ ] 3.2 Point the `Approved`-comment gate merges at the document PR whose
      base is the epic branch, and check agent stages out from the epic
      branch when `epics: true` (default branch otherwise); verify the
      squash-merge lands on `factory/epic-<n>` in a test repo.
- [ ] 3.3 Handle `factory:on-epic` in the label routing/authorization tables
      (no gate attached; `factory:in-staging` handling unchanged); verify
      `scripts/test-router.js` passes with new cases added for both policy
      values.
- [ ] 3.4 Extend the layer-3 provenance check description (§8a) so a `main`
      merge whose head is an epic branch is reported as skipping staging;
      verify the guard/audit wording matches FACTORY.md.
- [ ] 3.5 Implement in-flight adoption: when `epics: true` and an epic has no
      merged gate document, the gate-approval and stage-run paths create the
      epic branch if missing and retarget any open document PR base onto it
      before merging (and the reverse retarget on rollback to
      `epics: false`); verify against a test repo with a spec PR open against
      the default branch — after the flip, gate approval merges it into
      `factory/epic-<n>`, not `main`.

## 4. Verification and conformance

- [ ] 4.1 Add routing-matrix cases (document PR base, task PR base, stage
      checkout ref, integration/promotion targets × `epics` true/false) to
      `scripts/test-router.js` and/or `orchestrator/conformance`; verify all
      pass.
- [ ] 4.2 Run `hooks/protect-branches.py` unit checks against epic-branch
      pushes (allowed) and default-branch pushes (denied); add cases if the
      hook has none for `factory/epic-*`.
- [ ] 4.3 End-to-end dry run on a sandbox repo with `epics: true`: file an
      epic, confirm spec PR bases on `factory/epic-<n>`, gate-merge it,
      confirm the planner run reads the change folder from the epic branch;
      record the run trace in the wiki.

## 5. software-factory-view (sibling repo)

- [ ] 5.1 Add `factory:on-epic` to the label catalog, state order and gate
      map in `packages/core/src/factory.ts` and the phase map in
      `packages/core/src/phases.ts` (phase `shipping`, before
      `factory:in-staging`); verify `labels.test.ts` and core tests pass.
- [ ] 5.2 Render the new state in `PipelineBoard.tsx` / `EpicWorkspace.tsx`
      (column/badge for "on epic branch") and surface the epic branch name
      on the epic view; verify the web app builds and the board shows the
      state with fixture data.

## 6. Docs and migration

- [ ] 6.1 Update `docs/setup-guide.md` and the wiki pages
      (Factory-Pipeline-States, Release-Gating, Home) for the epic layer and
      the policy switch, including the migration note (in-flight epics finish
      on legacy routing); verify wiki publish script picks the pages up.
- [ ] 6.2 Write the estate migration checklist (flip `epics: true`
      estate-wide, label creation, automatic adoption of in-flight epics with
      unmerged gate documents vs. legacy finish for epics past a gate merge,
      rollback) as part of the setup guide; verify it matches design.md's
      Migration Plan and the adoption scenarios in
      `branching/epic-branches`.
