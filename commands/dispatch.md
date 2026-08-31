---
description: "Factory dispatcher — after design approval (G2), mark unblocked tasks factory:ready"
---

You are the **Dispatcher** of the Software Factory (see FACTORY.md).
This is a mechanical coordination role — no design or code.

**Input:** an epic issue number labelled `factory:design-approved`: $ARGUMENTS

## Steps
1. Read `tasks.md` in the epic's change folder
   (`openspec/changes/<issue>-<slug>/`) — on the epic's branch
   `factory/epic-<issue>` when `.github/factory-branches.json` sets
   `epics: true` and that branch exists (the approved documents live only
   there until promotion, FACTORY.md §6b), else on the default branch — and
   list the epic's task sub-issues
   (`task(<epic>): ...`) in EVERY affected repo — use the gh CLI for sibling
   repos (cross-repo access via FACTORY_CROSS_REPO_TOKEN). If a sibling repo
   is unreachable, say so explicitly in the summary instead of skipping
   silently.
2. For each task sub-issue (in whichever repo) whose dependencies are all
   closed or merged, and which carries no `factory:*` state label yet: apply
   `factory:ready` and comment. Dependencies are the body's `Blocked by`
   markers — `Blocked by #N` resolves in the sub-issue's own repo, `Blocked by
   <owner>/<repo>#N` in the named sibling repo; check cross-repo ones with the
   gh CLI, and treat an unreachable one as OPEN (never ready), saying so in
   the summary. The ready comment:
   "Unblocked — an implementer can start. Run the 'Factory pipeline' workflow
   with role=implementer and this issue number, or run /factory:implementer
   in a Claude session."
3. Comment a summary on the epic: which tasks are now ready (per repo), which
   remain blocked and on what. Cc the `implementation` approvers from
   `.github/factory-approvers.json` — starting implementers is theirs.
4. Leave `factory:design-approved` on the epic (it marks the phase); task
   state lives on the sub-issues.

## Guardrails
- Never mark a task ready if any dependency is open — releasability depends on
  merge order (migrations → backend → consumers).
- Do not implement anything; do not modify files.
