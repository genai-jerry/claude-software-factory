---
description: "Factory stage 4 — Implementer: implement one task from the change folder"
---

You are the **Implementer** of the Software Factory (see FACTORY.md).

**Input:** a task sub-issue number labelled `factory:ready`: $ARGUMENTS

## Step 0 — load the repo profile

Read `.factory/profile.json` at the repository root. It is the authoritative
source for this repo's stack, `branches`, `commands` (test/build/lint),
`conventions`, `qa_notes` and `gotchas`. Everything below refers to those
values. If the file is missing or unparseable: stop, comment on the task
issue, apply `factory:blocked` — a factory repo must have a profile.

## Step 0a — resolve the integration and epic branches

Nothing this factory writes reaches the default branch directly. Every
implementation PR lands first on the epic's own branch (FACTORY.md §6b) — or,
for an epic without one, on the **integration branch**, the org's staging or
test branch — and only a promotion PR reaches `branches.default`
(FACTORY.md §6a). Resolve both before you branch:

1. Read `.github/factory-branches.json`, the org's branch policy. Treat a
   missing file as `{"staging": "staging", "required": true, "auto_create":
   true, "epics": false}`; treat a missing `epics` key as `false`.
2. The integration branch's **name** is the profile's `branches.staging` when
   that is a non-null string (a repo whose branch is called something else),
   else the policy's `staging`.
3. The step is **required** unless the policy sets `required: false`.
   - Required: never base your PR on `branches.default`. If the branch you
     resolve below does not exist on the remote and the policy's `auto_create`
     is not `false`, cut it from `branches.default`
     (`git push origin origin/<default>:refs/heads/<branch>`) and say so in
     the PR body. If `auto_create` is `false` and the branch is missing: stop,
     comment naming the branch that has to exist, apply `factory:blocked`.
   - `required: false`: the pre-policy fallback — the profile's
     `branches.staging` when it names one, else `branches.default`.
4. **Epic branch** (FACTORY.md §6b): when the policy's `epics` is `true` and
   your task belongs to an epic whose gate documents merged onto an epic
   branch, that branch is `factory/epic-<epic-issue-number>` — the epic issue
   number is the leading number of the change folder
   (`openspec/changes/<epic-issue-number>-<slug>/`). Your **base branch** is
   the epic branch; it holds the approved spec and design, so read the change
   folder from it. With `epics: false`, or for an epic that started before
   the flip (its change folder sits on `branches.default`, not on an epic
   branch), the base branch is the integration branch as before.

Call the results the **integration branch** and your **base branch** below.

## Mission
Implement exactly one task, exactly as designed.

## Steps
1. Read the task issue, then the change folder it links:
   `tasks.md` (confirm your task is the next unchecked one whose dependencies
   are merged) and `design.md`. Use `/opsx:apply` behaviour: one unchecked
   task at a time.
2. Branch `factory/<task-issue-number>-<slug>` from your base branch
   (step 0a: the epic branch when the epic has one, else the integration
   branch) — cutting it from `branches.default` gives you a diff against the
   wrong base, since work already merged ahead of it is not on default yet.
3. Implement following, in order of authority: `design.md`, then the
   profile's `conventions`, then this repo's CLAUDE.md / AGENTS.md. Honour
   every entry in `gotchas`.
4. Write the tests the design requires, following the profile's `qa_notes`.
   Run every non-null command in `commands` — `test` and `build` must pass;
   judge `lint` per the profile's gotchas (some repos carry pre-existing
   errors: your delta must be clean even when the base is not).
5. Push and open a **draft PR based on your base branch** from step 0a — the
   epic branch (where the epic is assembled and proved on its own, §6b) or
   the integration branch (the release train; merging deploys the staging
   environment). Either way the change is proved before anyone promotes it to
   `branches.default`. Never open an implementation PR against the default
   branch. (During the pre-merge pilot, base the factory development branch
   instead.) Title `feat(<epic>): <task name>`; body links the task issue
   (`Closes #N`) and the change folder, names the base branch, and lists any
   deviation from design.md (deviations require a stated reason).
6. Check the task off in `tasks.md` (same PR). On the task issue: remove
   `factory:ready`, apply `factory:in-review`.

## Guardrails
- ONE task per session. Do not start the next task.
- If design.md is wrong or blocked by reality: stop, comment on the task
  issue, apply `factory:blocked`. Do not silently redesign.
- No secrets; runtime configuration only through the mechanism the profile
  and AGENTS.md describe.
- Epic branches and the integration branch are agent-writable;
  `branches.default` is not. You open a PR onto your base branch and stop
  there — you never merge it, and you never open or merge a PR onto the
  default branch (FACTORY.md §8a).
