# Add Epic Branch Strategy

## Why

Today the factory routes document PRs (spec, plan+design) straight to the
default branch and implementation PRs straight to the single shared
integration branch (`staging`). Two problems follow:

1. **Documents bypass staging semantics.** A spec PR (e.g.
   lighthouse-backend#251) targets `main` directly. That is by design today —
   later stages clone the default branch — but it means an epic's artifacts
   land on the production branch before a line of the epic's code has shipped,
   and there is no single branch that holds *everything* belonging to one epic.
2. **Epics cannot be tested in isolation.** All in-flight epics interleave on
   the one integration branch. One epic red on staging blocks every other
   epic's verification, and there is no way to deploy and test *just one
   epic's* changes before committing them to the shared release train.

The fix is a per-epic branch: every artifact an epic produces — spec PR,
plan+design PR, task PRs — merges first into that epic's own branch. Each epic
is developed, integrated, and testable independently. Only a *complete, green*
epic merges to the org integration branch (`staging`), and production release
remains the staging → default-branch promotion a human merges at gate G3.

## What Changes

- **New branch layer:** `factory/epic-<epic-issue-number>`, cut from the
  default branch when an epic enters the pipeline, deleted after its content
  reaches the default branch. Task branches are cut from it; spec, design and
  task PRs merge into it.
- **Document PR routing changes** (**BREAKING** for existing estates): spec
  PRs (`factory/<epic>-spec`) and plan+design PRs (`factory/<epic>-design`)
  base on the epic branch, not the default branch. Gate G1/G2 approval
  squash-merges them into the epic branch.
- **Stage checkouts follow the epic:** planner, architect, implementer,
  reviewer and qa work from the epic branch (that is where the approved change
  folder now lives), not from the default branch.
- **Release flow gains one hop:** Release Manager assembles task PRs onto the
  epic branch in dependency order, verifies the epic there (per-epic preview
  environment when the repo profile defines one), then opens and merges one
  **integration PR** epic → staging per repo. Staging verification and the
  human-merged staging → default promotion PR (gate G3) are unchanged.
- **New task/epic state** `factory:on-epic`: merged onto the epic branch and
  green there, awaiting the epic → staging integration merge.
  `factory:ready-to-ship` now promises "mergeable onto the *epic* branch";
  `factory:in-staging` keeps its meaning (on the integration branch,
  verified).
- **Branch policy extended:** `.github/factory-branches.json` gains
  `"epics": true|false` (default `false` for existing estates; the shipped
  template sets `true`). With `epics: false` the factory behaves exactly as
  today.
- **Epic branch freshness:** after any production promotion, the default
  branch is merged into every live epic branch so parallel epics do not rot
  against a moving baseline.
- **Unchanged:** fast-track PRs (no epic, still based on the integration
  branch), the protected-branch guard (default branch stays human-only; epic
  branches and the integration branch stay agent-writable), gate G3 as the
  only path to the default branch, and `/opsx:archive` after production soak.

## Capabilities

### New Capabilities

- `branching/epic-branches`: lifecycle of the per-epic branch — naming,
  when and from what it is created, how it is kept fresh against the default
  branch, agent writability, and when it is deleted.
- `branching/artifact-routing`: which branch every factory PR bases on and
  merges into — spec, plan+design, task, fast-track, integration
  (epic → staging) and promotion (staging → default) PRs — and which branch
  each pipeline stage checks out, under both `epics: true` and
  `epics: false` policy.
- `branching/epic-promotion`: the epic's path to production — dependency-
  ordered assembly on the epic branch, epic-level verification, the
  epic → staging integration PR, staging verification, the gate-G3 promotion
  PR, and the label states (`factory:on-epic`, `factory:in-staging`,
  `factory:deployed`) that track it, including cross-repo epics as one
  release train.

### Modified Capabilities

<!-- none: openspec/specs/ holds no synced capabilities yet; all behavior
     above is captured as new capabilities -->

## Impact

- **FACTORY.md**: §2 stage table, §2a triggers, §3 states table, §6
  branching, §6a integration branch (new §6b for epic branches), §7
  cross-repo epics, §10 setup steps.
- **Role prompts** (`commands/`): intake, planner, architect, implementer,
  reviewer, qa, release, dispatch, ops gain epic-branch resolution (a step
  0a-style preamble) and re-based PR targets; fasttrack gets an explicit
  "no epic branch" note.
- **Pipeline workflow** (`.github/workflows/factory-pipeline.yml`): create
  the epic branch at intake, merge gate document PRs into it on `Approved`,
  check stages out from it, and handle the new `factory:on-epic` state.
- **Templates**: `templates/factory-branches.json` (`epics` key),
  `scripts/setup-labels.sh` (new label).
- **Guard** (`hooks/protect-branches.py`): unchanged rules, but verify epic
  branches match the agent-writable pattern.
- **software-factory-view** (sibling repo): label catalog, state machine,
  phase mapping and gate table in `packages/core/src/factory.ts` /
  `phases.ts`, plus board/workspace UI that renders the new state.
- **Docs/wiki**: setup guide, Factory-Pipeline-States, Release-Gating pages.
- **Migration**: estates with in-flight epics keep `epics: false` until those
  epics ship; flipping the policy affects only epics entering intake after
  the flip.
