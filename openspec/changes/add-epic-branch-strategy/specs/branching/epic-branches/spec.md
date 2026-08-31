# Delta Spec: branching/epic-branches

## Purpose

Defines the lifecycle of the per-epic branch: the one branch that carries every
artifact an epic produces — spec, plan, design, and task merges — so each epic
can be built and verified in isolation before it joins the shared integration
branch.

## ADDED Requirements

### Requirement: Epic branch policy switch

The branch policy file `.github/factory-branches.json` SHALL accept a boolean
key `epics`. When `epics` is `true`, every epic entering the pipeline gets a
dedicated epic branch and all epic artifacts route through it. When `epics` is
`false` or the key is absent, the factory SHALL behave exactly as before this
change: document PRs base on the default branch and implementation PRs base on
the integration branch. The shipped template `templates/factory-branches.json`
SHALL set `epics: true`; the absent-file default SHALL remain `epics: false`.

#### Scenario: Policy absent keeps legacy behavior

- **WHEN** a repo has no `.github/factory-branches.json`, or the file omits the
  `epics` key
- **THEN** no epic branch is created for a new epic, and every role resolves PR
  bases exactly as it did before this change

#### Scenario: Policy enabled routes a new epic through an epic branch

- **WHEN** `epics` is `true` and an issue enters intake as an epic
- **THEN** an epic branch exists for that epic before its spec PR is opened,
  and all of the epic's subsequent PRs base on it

#### Scenario: Flipping the policy does not disturb in-flight epics

- **WHEN** `epics` is flipped from `false` to `true` while an epic is already
  past intake
- **THEN** that epic continues on its original (legacy) routing, and only
  epics entering intake after the flip get epic branches

### Requirement: Epic branch naming and creation

When `epics` is `true`, the factory SHALL create one branch named
`factory/epic-<epic-issue-number>` per epic in each affected repo, cut from
that repo's default branch at the moment the epic's first artifact needs it
(intake, before the spec PR is opened). For cross-repo epics the
`<epic-issue-number>` SHALL be the epic issue's number in the coordination
repo, so the branch name is identical across all affected repos. Creating a
branch that already exists SHALL be a no-op, not an error.

#### Scenario: Branch cut at intake

- **WHEN** the Intake Analyst starts on epic issue #42 and no
  `factory/epic-42` branch exists
- **THEN** `factory/epic-42` is created from the tip of the default branch
  before the spec PR is opened, and the spec PR's base is `factory/epic-42`

#### Scenario: Cross-repo epic uses one name everywhere

- **WHEN** epic #42 in the coordination repo affects repos A and B
- **THEN** both repos carry a branch named `factory/epic-42`, each cut from
  its own repo's default branch

#### Scenario: Re-run does not fail on an existing branch

- **WHEN** a stage re-runs for epic #42 and `factory/epic-42` already exists
- **THEN** the existing branch is used as-is and the run proceeds

### Requirement: Epic branches are agent-writable

Epic branches SHALL be writable by factory agents: the protected-branch guard
SHALL continue to block only the default branch set (`main`/`master`), and
SHALL NOT block pushes or merges targeting `factory/epic-*` branches or the
integration branch.

#### Scenario: Agent merge into an epic branch passes the guard

- **WHEN** an agent merges a task PR whose base is `factory/epic-42`
- **THEN** the protected-branch guard allows the operation

#### Scenario: Default branch stays human-only

- **WHEN** an agent attempts to push to or merge a PR into the default branch
- **THEN** the guard blocks the operation, exactly as before this change

### Requirement: Epic branches are kept fresh against the default branch

After any promotion PR merges to the default branch, the factory SHALL merge
the default branch into every live epic branch in that repo (a merge, never a
rebase or force-push). A merge conflict SHALL NOT be resolved silently: the
epic SHALL be marked `factory:blocked` with a comment naming the conflicting
files, for the epic's agents or a human to resolve on the epic branch.

#### Scenario: Parallel epic refreshed after another epic ships

- **WHEN** epic #40's content reaches the default branch while
  `factory/epic-42` is still live
- **THEN** the default branch is merged into `factory/epic-42`, and the epic's
  subsequent task branches and verification include epic #40's shipped changes

#### Scenario: Refresh conflict blocks the epic visibly

- **WHEN** merging the default branch into `factory/epic-42` conflicts
- **THEN** epic #42 is labelled `factory:blocked` with a comment listing the
  conflicting paths, and no history rewrite occurs on `factory/epic-42`

### Requirement: Epic branch deletion

An epic branch SHALL be deleted only after the epic's content has reached the
default branch (its promotion PR merged) or the epic issue is closed without
shipping. Deletion SHALL happen during the Ops Monitor's archive step, never
earlier.

#### Scenario: Deleted after successful release

- **WHEN** the Ops Monitor archives epic #42 after production soak passes
- **THEN** `factory/epic-42` is deleted in every affected repo

#### Scenario: Preserved while anything is unshipped

- **WHEN** epic #42 is on the integration branch but its promotion PR has not
  merged
- **THEN** `factory/epic-42` still exists
