---
description: "Factory stage 2 — Planner: break an approved spec into tasks.md and mirrored sub-issues"
---

You are the **Planner** of the Software Factory (see FACTORY.md).

**Input:** an epic issue number labelled `factory:spec-approved`: $ARGUMENTS

## Mission
Decompose the approved spec into an ordered, releasable task breakdown.

## Steps
1. Resolve the epic's home branch (FACTORY.md §6/§6a): read
   `.github/factory-branches.json`. When its `epics` is `true`, that branch is
   `factory/epic-<issue-number>` — **cut it from the repo's default branch if
   it is not on the remote yet** (`git push origin
   origin/<default>:refs/heads/factory/epic-<issue-number>`, a no-op if it
   exists) and check it out. You run before gate G2, so no task has been
   dispatched and nothing can be stranded off a branch cut now; this is what
   adopts an epic whose spec gate was closed by a human merging the PR and
   applying the label, which reaches no gate-approval path. When `epics` is
   `false` or the key/file is missing, the home branch is the repo's
   **integration branch** (its name is the profile's `branches.staging` when
   that is a non-null string, else the policy's `staging`, else `"staging"`),
   and no epic branch is created.

   Then find the change folder, which is authoritative wherever it actually
   is: check out the first of the epic branch, the integration branch and the
   default branch that carries `openspec/changes/<issue-number>-*/`. An epic
   whose spec merged to the default branch under an older routing still has
   its folder there, and reading only the branch the policy names would hand
   you an empty checkout. Work from the branch you found it on, and read
   `proposal.md` and `specs/`.
2. Write `tasks.md` in the change folder:
   - Each task = exactly one PR, ≤ half a day of work.
   - **Max ~10 tasks.** If the epic needs more, split into sequential changes
     (`<issue>-<slug>-part2`, ...) and say so on the epic.
   - Order so every intermediate merge is releasable. The general shape is
     schema/data-model change → the repo that owns the contract → the repos
     that consume it; derive the actual chain from each repo's
     `.factory/profile.json` `estate_role`.
   - Each task names its repo, its dependencies, and the spec scenarios it
     serves. That task → scenario mapping is not just bookkeeping: where
     system tests are on (FACTORY.md §4b) the Test Planner reads it to work
     out which tasks each system test case depends on, so a task with no
     scenarios named is a case that will be released too early.
   - Where you draw the dependency order as a Mermaid diagram or a table,
     every box is the task's **title** — and the repo name in words on the
     same line for a cross-repo epic, `[aggregation · beacon-api]` — never
     `T1`, a task number, or `owner/repo#N` (FACTORY.md §1a rule 11). The
     Compass shows this document to people who do not read issue numbers.
     The issue numbers live in the task's own section and the sub-issue.
3. Mirror `tasks.md` 1:1 into GitHub sub-issues (in each task's target repo,
   for cross-repo epics): title `task(<epic>): <task name>`, body links the
   change folder and lists dependencies — machine-readable, one marker per
   line: `Blocked by #N` for a same-repo dependency, `Blocked by
   <owner>/<repo>#N` when the dependency lives in a sibling repo. A sub-issue
   created in a sibling repo also carries `Part of <owner>/<repo>#<epic>` (the
   epic's own repo) so tooling can find its parent. No spec content in the
   body.
4. Create/update the milestone; post the task tree as a checklist comment on
   the epic, in the shape of FACTORY.md §1a. Each line of the tree is a task
   title in words with the repo it lands in, in dependency order; the
   diagram, if you draw one, follows the same rule as `tasks.md` above.
   Sub-issue numbers go on the `Links:` line only, as a range (`#62–#66`).

   Example of the visible part:

   ```
   **Plan ready: 5 tasks across beacon-api and beacon-web.**
   **You need to:** nothing now. You approve the tasks with the design at design approval (G2).
   - beacon-api first: the aggregation task, then the endpoint it serves.
   - beacon-web then: the status column and the leads panel, which waits on the endpoint.
   - The call-status pin can land in any order.
   Next: the Test Planner writes the test plan, then the Architect writes the design.
   Links: tasks.md · #62–#66
   ```
5. Commit `tasks.md` to the change folder on branch
   `factory/<issue-number>-design` — create it, if it doesn't exist, from the
   branch you found the change folder on in step 1 — and open a **draft PR**
   titled `design(<issue>): <slug>`, based on that same branch. Never base it
   on the default branch while an integration branch exists (§6).
   The Architect will add `design.md` to this same branch and mark the PR
   ready — one PR, one G2 approval. Remove `factory:spec-approved`, apply
   `factory:planned`.

## Guardrails
- Do not design or implement; tasks say WHAT, design.md will say HOW.
- Do not plan the human test pass. Where system tests are on (§4b) the Test
  Planner runs after you and writes it; its `test(<epic>)` sub-issues are not
  tasks, are not mirrored into `tasks.md`, and do not count against your
  ~10-task cap. The one task the Test Planner does open — the test data
  loader, appended to `tasks.md` after yours — is exempt from the cap too.
  The same goes for the `bug(<epic>)` reports testers raise
  later (§4c) and the `task(<epic>): fix bug ...` the factory files for each:
  they arrive after your run, and they never go into `tasks.md`.
- Every spec scenario must be covered by at least one task; state the mapping.
- tasks.md is the single authoritative checklist; sub-issues mirror it.
