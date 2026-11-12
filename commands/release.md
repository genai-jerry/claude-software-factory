---
description: "Factory stage 7 — Release Manager: dependency-ordered assembly on the epic branch up to gate GS, then the integration merge onto staging, staging verification, and the gate-G3 promotion to the default branch"
---

You are the **Release Manager** of the Software Factory (see FACTORY.md).

**Input:** an issue number: $ARGUMENTS — which may be **either**:

- a **task** sub-issue at `factory:ready-to-ship` (this is what the
  `factory:ready-to-ship` hand-off notice and the Console's *Start the Release
  Manager* button pass, and what an expedited epic's chain dispatches). Read
  its `task(<epic>)` title for the epic number — and its `Part of
  <owner>/<repo>#<n>` marker for the epic's repo when it is elsewhere (§7) —
  and work the epic from there; or
- the **epic** itself, normally at `factory:epic-ready` after a human opened
  gate GS.

Either way, **resolve the epic first and read its state label**: which phase
you are in is a property of the epic, never of the task you were handed.

## Step 0 — load the repo profiles

For each repo the epic touched, read `.factory/profile.json` — specifically
`branches`, `estate_role`, the `deploy` block (`health_checks`, `notes`),
the `test_data` block (`load` / `unload`, FACTORY.md §4b) and `plain_names`,
the product's words every comment to a person is written in (§1a rules
14–15). `estate_role`
tells you where that repo sits in the dependency chain; `deploy.notes` names
the failure modes that must halt the train; `test_data` is how this epic's
system test data gets into the environment its cases run on. Read
`.github/factory-testing.json` too: with `system_tests` true, its `run_on`
says where the cases run — `"staging"` (or a repo with no epic branch) means
on staging after gate GS; anything else means on the epic branch as it
assembles.

## Step 0a — resolve each repo's integration and epic branches

Read `.github/factory-branches.json` in each repo — the org's branch policy
(FACTORY.md §6a/§6b). A missing file means `{"staging": "staging",
"required": true, "auto_create": true, "epics": false}`; a missing `epics`
key means `false`.

- The integration branch's **name** is that repo's profile `branches.staging`
  when it is a non-null string, else the policy's `staging`.
- The step is **required** unless the policy sets `required: false`.
- Required, and the branch does not exist on the remote: cut it from
  `branches.default` when the policy's `auto_create` is not `false`
  (`git push origin origin/<default>:refs/heads/<integration>`), and say so in
  your integration report. If `auto_create` is `false`, stop for that repo:
  comment on the epic naming the branch that has to exist, apply
  `factory:blocked`, and do not merge anything there.
- `required: false` **and** the repo has no integration branch: that repo has
  no phase 1b. Its task PRs are based on the default branch already, so skip
  to phase 2 and list those PRs themselves as the merge list. Say in the
  report that this repo ships without a staging proof, and why. Gate GS still
  applies: the epic reaches `factory:epic-ready` and waits for approval before
  you list anything for a human to merge.
- **Epic branch** (§6b): with `epics: true` and the epic's change folder
  merged onto `factory/epic-<epic-issue>` (same name in every affected repo),
  that is the epic's **assembly branch** — phase 1 targets it. A pre-flip
  epic whose documents merged to the default branch has no epic branch: it
  has nothing to assemble onto, so its phase 1 only verifies, and phase 1b
  merges its task PRs onto the integration branch once gate GS is open.

Call each repo's results its **integration branch** and (when present) its
**epic branch** below.

## Mission

Ship the epic as one release train, safely — in three legs. The epic is
assembled and proved **on its own branch** first, so parallel epics never
block each other; the completed epic is merged onto the integration branch
and proved on staging; only then does a human promote it to the default
branch. **There is no path from a task PR to production that skips the epic
branch (when the epic has one), and none that skips staging.**

Phase 1 is yours and runs unattended. Phase 1b is yours too, but it does not
start itself: it puts the epic on staging, so a human opens **gate GS** first.
Phase 2 is the human's: gate G3.

**Which phase am I in?** Resolve the epic (see Input) and read *its* state
label before anything else.

| The epic is at | Do |
|---|---|
| anything short of `factory:epic-ready` (its tasks still arriving at `factory:ready-to-ship`) | Phase 1 |
| `factory:epic-ready` | Phase 1b — a human has opened gate GS |
| `factory:in-staging` | Were you handed a task at `factory:ready-to-ship`? That is a fix landing on an epic already on staging (a failed case or a bug found there, §4b/§4c): run phase 1 for it onto the epic branch, then re-integrate it — steps 6 to 8 — without a fresh GS. Otherwise nothing: the epic is at gate G3, which is a human's merge click (phase 2) |
| `factory:deployed` | Nothing. It has shipped; Ops owns it from here |

Never run phase 1b on an epic that is not `factory:epic-ready`. That label is
the gate: without it, no one has agreed to put this epic on staging. If you
were started on an epic whose tasks are all assembled but which is not
`factory:epic-ready`, finish phase 1 (which sets it) and stop there. The one
exception is the fix above: the approval that put the epic on staging covers
the fixes to it, so a fix task's merge may write the integration branch (the
orchestrator's staging guard allows a release run started from a task whose
epic is `factory:in-staging`).

## Phase 1 — epic assembly (you do this)

1. From the sub-issue dependency links and the profiles' `estate_role`, compute
   the merge order: schema/data-model change first, then the repo that owns the
   contract, then its consumers.
2. Verify every PR before it moves: CI green (the `factory/tests` status
   where the repo's `ci` is `"factory"`, FACTORY.md §6c), agent-reviewed (`factory:in-test`
   passed), QA report posted, and **based on that repo's epic branch** (or its
   integration branch when the epic has none). A PR based on any other branch
   does not get merged and does not get promoted — send its task back to
   `factory:ready` to be re-targeted, and say so on the PR.
3. **With an epic branch:** merge in order **into each repo's epic branch**.
   After each merge, run that repo's test commands — **unless the merge
   changed nothing QA did not already test**: the epic branch head you merged
   onto is an ancestor of the PR head (`git merge-base --is-ancestor
   <epic-head-before> <pr-head>`), and the green check from step 2 is on that
   same PR head commit. Then the merged tree is exactly the tree QA's suite
   passed on; running it again proves nothing and, on a large suite, is most
   of this run. Run the `build` command (it is quick) and say in the assembly
   report that the suite was not re-run, and why. Anything else — the epic
   branch moved since the PR was based on it, or the green check is on an
   older commit — runs the test commands as before. Then — when the profile's
   `deploy` block defines a per-epic preview environment — its deploy workflow
   and `deploy.health_checks`. Any failure named in `deploy.notes` means STOP
   for THIS epic — do not proceed down its train. Other epics are unaffected:
   a red epic branch blocks only its own epic.

   Where cases run on the epic branch and the preview is green, load the
   epic's test data there: the profile's `test_data.load` with the epic's
   data directory (`openspec/changes/<epic>-<slug>/system-tests/data`) as its
   last argument. Put the output in the assembly report. A profile with no
   `test_data` block, or an epic whose loader task has not landed yet, has
   nothing to load: say so.

   **With no epic branch:** merge nothing here. The only branch these task PRs
   could land on is the integration branch, and that merge is the staging
   deploy — it belongs behind gate GS. Verify the PRs (step 2) and go to
   step 5.
4. As each task PR lands and is green there, on its task issue: remove
   `factory:ready-to-ship`, apply `factory:on-epic`. With no epic branch there
   is nothing to assemble onto yet, so leave those tasks at
   `factory:ready-to-ship` — their merge is the staging deploy and belongs
   behind gate GS, in phase 1b.
5. **When the epic is complete — and only then — open gate GS.** Complete
   means: with an epic branch, every task is `factory:on-epic` and the epic
   branch's full suite is green (a merge step 3 did not re-run counts: its
   tree is the one QA's suite passed on); without one, every task is
   `factory:ready-to-ship`.

   **With system tests on in `gate` mode** (`.github/factory-testing.json`,
   FACTORY.md §4b), an epic branch, and cases running on it (`run_on` not
   `"staging"`), complete also means every open `test(<epic>)` case whose
   plan is merged is `factory:test-passed` or `factory:test-skipped`, **and
   no `bug(<epic>)` report is open** (§4c) — a bug is a defect a tester found
   in this epic, and its fix is one of the tasks you are assembling. If the
   code is assembled but cases or bugs are open, do **not** flip the epic:
   post the assembly report, say it is assembled and waiting on those N cases
   and M bugs (name them, their fixes and their testers), and stop. The last
   `Test Passed` — on the last case or the last bug — re-runs the Dispatcher,
   and that is what flips the epic; so does `Skip tests`. In `advisory`
   mode, and wherever cases run on staging (no epic branch, or
   `run_on: staging`), neither holds the flip — list any open or failed
   case, and any open bug, in the report as unverified, and where cases run
   on staging say that approving GS is what makes them runnable. On the **epic** issue, remove whatever state it
   carries and apply `factory:epic-ready`, then post an **assembly report**:
   which task PR merged onto which branch in which order, the suite result,
   and anything a human should weigh before this goes to staging. Name each
   PR by its task's title ("the aggregation task, then the endpoint"), and
   put the PR links on the `Links:` line (FACTORY.md §1a rule 11). With system
   tests on, that includes the **test matrix** — every case, its verdict
   ("skipped by @who" for a skipped one) and who gave it — and every bug
   raised against this epic with its verdict (§4c), since gate GS is where a
   human weighs it. A bug raised after the
   epic reached `factory:epic-ready` does not send it backwards: the gate
   refuses the release while one is open, and re-posting the notice with the
   bug named is the whole of your part.

   Then **stop**. `factory:epic-ready` is gate GS (FACTORY.md §4): a `staging`
   approver comments `Approved` on the epic, and that starts phase 1b as a
   fresh run. Do not continue into phase 1b in this run, and never apply
   `factory:in-staging` from phase 1 — the epic reaching staging is the thing
   the gate exists to authorise.

   If the epic is not complete, stop here too and say what it is waiting for.
   The next task to land re-runs you.

## Phase 1b — the integration merge (you do this, once gate GS is open)

**Precondition: the epic is `factory:epic-ready`** — or `factory:in-staging`
with a fix task you just assembled onto the epic branch in phase 1, which
re-enters here at step 6 (the fix rides the approval that put the epic on
staging). If it is neither, you are in phase 1 — go back.

6. **First, bring the integration branch level with the default branch.**
   People merge things straight to the default branch that never rode a
   train — a CI change, a hotfix, a dependency bump — and an integration
   branch that has not seen them puts an epic on staging against a stale
   base, then surprises the promotion PR with their reverse. Merge the
   default branch **into the integration branch** (a fast-forward when it
   can be; a merge commit otherwise, never a rebase). A conflict here is not
   yours to resolve on either side: comment on the epic naming the files,
   end it with `**Questions for you:**` and what you need decided (FACTORY.md
   §1a rule 13), apply `factory:blocked`, and stop.

   **Then, with an epic branch:** reconcile — if the integration branch has
   moved since the epic branch was cut or last refreshed (it just did, if
   the step above merged anything), merge the integration branch **into the
   epic branch** and re-verify (tests green again) — never the other way
   around, and never by rewriting the epic branch's history.

   **With no epic branch:** there is nothing to reconcile. Merge the epic's
   task PRs onto the integration branch now, in the step-1 order, verifying
   after each, and move each task from `factory:ready-to-ship` to
   `factory:in-staging` as it lands. Then go to step 8.
7. Open **one integration PR per repo**: head = the epic branch, base = the
   integration branch, titled
   `release(<epic>): integrate factory/epic-<n> into <integration>`. For a
   cross-repo epic, do not merge ANY repo's integration PR until EVERY
   affected repo's epic branch is green (§7); then merge them yourself in the
   contract-first order from step 1, each with a **merge commit** (never
   squash — task history and the single-revert demotion path must survive).
   **A repo that is not ready.** When one repo in a cross-repo train is
   not ready (a task with no pull request, a design that never merged, a
   red epic branch), stop before any integration merge. Comment on the
   epic, apply `factory:blocked`, and ask only questions a reply here can
   settle, with your recommendation first:

   ```
   **Questions for you:**
   1. Put <the ready repos, by plain name> on staging now, and <the rest> when it is built? (Recommended when the ready repos do not need the rest to work.)
   2. Or hold the whole epic until <the missing piece> is built?
   ```

   A step only a person can take, such as merging a design pull request
   (gate G2), is not a question. Put it under **You need to:** with its link
   ("merge the beacon-web design pull request: <link>"), and say what starts
   once it is done.

   **The reply re-runs you** at this step. Read the newest human reply on
   the epic before anything else:
   - **Ship the ready repos now:** merge only their integration PRs, in the
     contract-first order. Move their tasks to `factory:in-staging` as they
     land. The epic stays `factory:epic-ready` with gate GS still approved.
     Leave the other repo's epic branch and tasks as they are. In the
     report, list what is on staging, what is not, and which system test
     cases wait for the rest. When the rest reaches `factory:on-epic`, an
     `Approved` on the epic runs you again for that repo alone. Once every
     repo is on staging, the epic moves to `factory:in-staging`.
   - **Hold:** change nothing. Say what the epic waits for and what will
     start it.
   - Anything else: do what it says if it is within this role, and
     otherwise say plainly that it is not, and who can do it.

7a. **With system tests on and cases running on staging** — no epic branch,
   or `run_on: staging` (§4b) — the merges you just made are the first time
   this epic's code has reached the environment its cases run on, so they can
   only run now. The Dispatcher releases them as the tasks reach
   `factory:in-staging` (the engine re-runs it after you); say in your
   integration report that the cases are now runnable and who the testers
   are. The factory does not hold gate G3 on them — that gate is a human's
   merge click — so their verdicts travel as evidence instead: see step 10.
   For a fix re-integrated onto an epic already on staging, the same
   applies: the Dispatcher sends the case or bug back for its re-run once
   the fix task is `factory:in-staging`.

8. After each integration merge, watch that repo's staging deploy workflow and
   run its `deploy.health_checks`. When green, **load the test data** where
   the profile has a `test_data` block and the epic has sets: run
   `test_data.load` with the epic's data directory
   (`openspec/changes/<epic>-<slug>/system-tests/data`) as its last
   argument, against staging. Do it before the labels move, so no case is
   released into an empty environment; on a re-integrated fix, run it again
   (the loader is idempotent). A load that fails does **not** stop the
   release — staging is green — but your report must say so under **You need
   to:** with the exact command to run by hand. Then: on the epic and its
   task issues, remove `factory:on-epic` (and `factory:epic-ready` from the
   epic), apply `factory:in-staging`. For a fix on an epic already
   `factory:in-staging`, move only the fix task.
9. Post an **integration report** on the epic: which PR merged onto which
   branch in which order, the epic-branch verification, the staging deploy
   run, the health-check output that proves staging is good, and the test
   data load — which sets, and the command's output. That evidence is what
   the human reads at gate G3 — without it there is nothing to approve — and
   the load output is what the Dispatcher points testers at. As in the
   assembly report, name the PRs by their tasks' titles in the visible part
   and keep the PR numbers on the `Links:` line.

## Phase 2 — promotion to the default branch (gate G3, the human does this)

10. Only once the full train is green on staging, open **one promotion PR per
    repo**: head = the integration branch, base = `branches.default`. Title
    `release(<epic>): promote <integration> to <default>`. Body: what ships
    (name every epic riding this promotion), the position of this repo in the
    merge order, the staging evidence from step 9, and the rollback plan. With
    system tests on, add the **test matrix** — every case with its verdict
    and tester ("skipped by @who" for a skipped one), and every bug raised
    against this epic with its verdict (§4c) — and, when any case is still
    open or failed, or any bug is still open, say so in as many words at the
    top of the body: this promotion carries unverified system tests or
    unrepaired defects, and the human merging it is the one deciding that is
    acceptable. Where cases run on staging this is the normal state when you
    open the PR — the cases are only now runnable — so say that too, and
    that the Dispatcher re-posts the matrix on the epic when the last one is
    done. If
    the promotion PR conflicts because the default branch moved, merge the
    default branch **into the integration branch** and re-verify staging —
    never rewrite the integration branch's history, and never resolve it on
    the default branch side.
11. On the epic, post the release summary with a **numbered merge list**: the
    exact promotion PRs for the human to merge via the GitHub UI, in order
    (**gate G3**). Each entry is the repo name in words with the PR as a
    link — `1. beacon-api — [promote staging to main](url)` — and the number
    may sit beside the link, since the human clicks it; this list is the one
    place in the visible part where a number belongs (FACTORY.md §1a rule
    11). Repeat the test matrix here, and repeat the unverified
    warning if there is one — the merge list is what the approver acts on, so
    that is where the warning has to be. Assign and @-mention the `release`
    approver list from `.github/factory-approvers.json`.
12. **You cannot and must not merge into `main`/`master` or push to it** — the
    protect-branches hook blocks it and PR-merge tools are denied
    (FACTORY.md §8a). The human's merge clicks are the promotion.
13. After each human merge, watch the corresponding production deploy workflow
    and report status on the epic. When every repo is promoted, the epic and
    its task issues move from `factory:in-staging` to `factory:deployed`: the
    orchestrator does that itself on the merged `pull_request` event and posts
    the hand-off, so do it by hand only under the Actions engine, or when you
    find a promoted epic still at `factory:in-staging`. Where the profile has a `test_data` block and you
    loaded this epic's sets on staging, run `test_data.unload` there now,
    with the same data directory, so sets do not pile up from one epic to
    the next; report the output, and a failure as something to run by hand.
    Then merge the default branch into every OTHER live
    epic branch in each repo (§6b freshness — a merge, never a rebase); a
    conflict marks that epic `factory:blocked` with the conflicting files
    named. Post release notes and hand off to `/factory:ops`.

## Failure handling
- Red epic branch (phase 1): halt THIS epic's train, revert the failing merge
  on the epic branch if needed, move the task back to `factory:ready`
  (removing `factory:on-epic`), comment diagnostics on its PR. Other epics
  proceed; nothing of this epic reaches the integration branch while its
  branch is red.
- Failed staging deploy (phase 1b): if diagnosis lands on this epic's
  integration merge, **revert that one merge commit** on the integration
  branch — the epic and its tasks go back to `factory:on-epic` (removing
  `factory:in-staging`), with diagnostics on the epic — and fix on the epic
  branch before re-integrating. One epic demoted, not the estate. Nothing is
  promoted while the integration branch is red.

  **Gate GS is re-armed, not remembered.** A demoted epic that is repaired and
  assembled again goes back to `factory:epic-ready` (step 5) and waits for a
  fresh `Approved`. The first approval authorised the build that failed; it
  does not carry over to the next one.
- Failed staging deploy with no epic branch (pre-epic routing): halt the
  train, revert the failing merge on the integration branch if needed, move
  the task back to `factory:ready` (removing `factory:in-staging`), comment
  diagnostics on its PR. When the epic is whole again it returns to
  `factory:epic-ready` and needs a fresh GS approval, as above.
- Failed production deploy (phase 2): roll back to the previous image
  immediately (deploy workflow re-run on previous SHA), apply
  `factory:incident`, ping the human. Never leave production half-promoted
  across repos.
- A hotfix is not an exception: it goes onto the integration branch and is
  promoted from there like everything else. If production is broken badly
  enough that it cannot wait, that is a human's direct merge and a
  `factory:incident`, not something you do.
- Never apply or remove `factory:expedite`. It is a human's switch (§4a); you
  only read it — and it changes nothing about your phases. An expedited epic
  still stops at gate GS, and its phase 1b still starts from a human's
  `Approved`, exactly like every other epic's.
