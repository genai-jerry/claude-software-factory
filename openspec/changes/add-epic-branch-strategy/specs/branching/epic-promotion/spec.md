# Delta Spec: branching/epic-promotion

## Purpose

Defines an epic's path from its own branch to production: dependency-ordered
assembly and verification on the epic branch, one epic → integration PR per
repo, staging verification, and the human-merged promotion to the default
branch at gate G3 — with the label states that make each step observable.

## ADDED Requirements

### Requirement: Tasks assemble on the epic branch in dependency order

When `epics` is `true`, the Release Manager SHALL merge an epic's
`factory:ready-to-ship` task PRs into the epic branch in the dependency order
derived from sub-issue `Blocked by` links, running the repo's test commands
(and deploy health checks when a per-epic preview environment is configured in
the repo profile) after each merge. A red epic branch SHALL halt further
merges for that epic only; other epics SHALL be unaffected.

#### Scenario: Green task lands on the epic branch

- **WHEN** task #57 of epic #42 is `factory:ready-to-ship` and its
  dependencies are already on `factory/epic-42`
- **THEN** the Release Manager merges PR #57 into `factory/epic-42` and the
  epic branch's checks run against the merged result

#### Scenario: A red epic blocks only itself

- **WHEN** `factory/epic-42` goes red after a merge while epic #43 is also in
  flight
- **THEN** epic #42's remaining merges halt and the failing task returns to
  `factory:ready` with diagnostics, while epic #43's assembly and promotion
  proceed untouched

### Requirement: Task state on the epic branch is observable

A new label `factory:on-epic` SHALL mark a task whose PR has merged into the
epic branch and is green there, awaiting the epic's integration merge. The
transition SHALL be: `factory:ready-to-ship` → (merge onto epic branch) →
`factory:on-epic` → (epic merges to integration) → `factory:in-staging`.
When every task of the epic is `factory:on-epic` and the epic branch is green,
the epic issue itself SHALL be marked `factory:on-epic`. Under
`epics: false` the label SHALL NOT be used and the legacy transition
(`factory:ready-to-ship` → `factory:in-staging`) SHALL remain.

#### Scenario: Label follows the merge

- **WHEN** task #57's PR merges into `factory/epic-42` and the epic branch is
  green
- **THEN** task #57 loses `factory:ready-to-ship` and gains
  `factory:on-epic`

#### Scenario: Epic marked when complete on its branch

- **WHEN** the last open task of epic #42 reaches `factory:on-epic` and the
  epic branch's full test suite is green
- **THEN** epic #42 is marked `factory:on-epic` and becomes eligible for the
  integration merge

### Requirement: One integration PR carries the epic to the integration branch

When an epic is complete and green on its branch, the Release Manager SHALL
open one **integration PR** per affected repo — head: the epic branch, base:
the integration branch — titled `release(<epic>): integrate factory/epic-<n>
into <integration>`, and merge it (a merge commit, preserving task history) only
after: (a) the integration branch has first been merged *into* the epic branch
and the epic re-verified when the two have diverged, and (b) every affected
repo's epic branch is green. Merging the integration PR SHALL move the epic
and its tasks to `factory:in-staging`. The epic branch's history SHALL never
be rewritten to resolve divergence.

#### Scenario: Divergence resolved on the epic side first

- **WHEN** another epic has merged to the integration branch since
  `factory/epic-42` was cut or last refreshed
- **THEN** the integration branch is merged into `factory/epic-42`, the epic
  re-verified green, and only then is epic #42's integration PR merged

#### Scenario: Cross-repo epic integrates as one train

- **WHEN** epic #42 spans repos A and B and only repo A's epic branch is green
- **THEN** neither repo's integration PR is merged until both epic branches
  are green, and integration merges follow the contract-first order derived
  from the profiles' `estate_role`

#### Scenario: States flip on integration

- **WHEN** epic #42's integration PR merges and the staging deploy and health
  checks pass
- **THEN** the epic and its tasks move from `factory:on-epic` to
  `factory:in-staging`, and the integration report is posted on the epic

### Requirement: Production release remains the gate-G3 promotion

Promotion SHALL remain one integration-branch → default-branch PR per repo,
opened by the Release Manager only when the full train is green on staging and
merged only by a human (gate G3). The promotion PR body SHALL name the epics
it carries and their staging evidence. A staging failure after an epic's
integration merge SHALL be handled on the integration branch (revert the
epic's integration merge commit if needed, returning the epic to
`factory:on-epic`), never by rewriting history and never on the default
branch.

#### Scenario: Promotion carries multiple completed epics

- **WHEN** epics #42 and #43 are both `factory:in-staging` and staging is
  green
- **THEN** one promotion PR per repo is opened whose body lists both epics
  with their staging evidence, and a human merge at G3 releases them together

#### Scenario: Staging failure demotes the epic, not the estate

- **WHEN** staging goes red and diagnosis attributes the failure to epic
  #42's integration merge
- **THEN** that merge commit is reverted on the integration branch, epic #42
  returns to `factory:on-epic` with diagnostics on the epic issue, and no
  promotion PR opens while staging is red
