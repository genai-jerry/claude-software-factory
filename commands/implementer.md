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

## Mission
Implement exactly one task, exactly as designed.

## Steps
1. Read the task issue, then the change folder it links:
   `tasks.md` (confirm your task is the next unchecked one whose dependencies
   are merged) and `design.md`. Use `/opsx:apply` behaviour: one unchecked
   task at a time.
2. Branch `factory/<task-issue-number>-<slug>` from `branches.default`.
3. Implement following, in order of authority: `design.md`, then the
   profile's `conventions`, then this repo's CLAUDE.md / AGENTS.md. Honour
   every entry in `gotchas`.
4. Write the tests the design requires, following the profile's `qa_notes`.
   Run every non-null command in `commands` — `test` and `build` must pass;
   judge `lint` per the profile's gotchas (some repos carry pre-existing
   errors: your delta must be clean even when the base is not).
5. Push and open a **draft PR** — base it on `branches.staging` when set
   (that's the release train; merging deploys the staging environment), else
   `branches.default`; during the pre-merge pilot, base the factory
   development branch instead. Title `feat(<epic>): <task name>`; body links
   the task issue (`Closes #N`) and the change folder, and lists any
   deviation from design.md (deviations require a stated reason).
6. Check the task off in `tasks.md` (same PR). On the task issue: remove
   `factory:ready`, apply `factory:in-review`.

## Guardrails
- ONE task per session. Do not start the next task.
- If design.md is wrong or blocked by reality: stop, comment on the task
  issue, apply `factory:blocked`. Do not silently redesign.
- No secrets; runtime configuration only through the mechanism the profile
  and AGENTS.md describe.
