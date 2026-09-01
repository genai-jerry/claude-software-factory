# Delta Spec: branching/artifact-routing

## Purpose

Where an epic's documents live, and where the stages that read them look.
This delta closes the one path by which content reaches the default branch
without a promotion PR.

## MODIFIED Requirements

### Requirement: Document PR base branches

Document PRs — the spec PR `factory/<epic>-spec` and the plan+design PR
`factory/<epic>-design` — SHALL base on the first branch that applies:

1. the epic branch `factory/epic-<epic>`, when the policy sets `epics: true`;
2. otherwise the repo's **integration branch**, resolved per §6a (the
   profile's `branches.staging` when it is a non-null string, else the
   policy's `staging`, else `"staging"`);
3. otherwise — only when the policy sets `required: false` and the repo has
   no integration branch — the repo's default branch.

They SHALL NOT base on the default branch while an integration branch exists.
The branch each PR is cut from SHALL be the same branch it targets. Gate G1
and G2 approval squash-merges them there.

#### Scenario: epics false sends the spec PR to the integration branch

- **WHEN** a repo sets `epics: false` with an integration branch `staging`
  and the Intake Analyst opens the spec PR for epic #5
- **THEN** `factory/5-spec` is cut from `staging` and its PR bases on
  `staging`, not on the default branch

#### Scenario: no integration branch keeps default-branch routing

- **WHEN** the policy sets `required: false` and the repo has no integration
  branch
- **THEN** document PRs base on the default branch, exactly as before this
  change

#### Scenario: epics true is unchanged

- **WHEN** the policy sets `epics: true`
- **THEN** document PRs base on `factory/epic-<epic>` exactly as before

### Requirement: Profile PR base branch

The profile PR carrying `.factory/profile.json` SHALL base on the repo's
integration branch when one exists, and on the default branch only when the
policy sets `required: false`. It has no epic and therefore never bases on an
epic branch. It reaches the default branch with everything else, at gate G3.

#### Scenario: the profile follows the branch its readers check out

- **WHEN** the Profiler opens or updates a profile PR in a repo with an
  integration branch
- **THEN** the PR bases on the integration branch, so a role checking that
  branch out reads the same profile the PR proposes once merged

### Requirement: Stage checkout resolution

Every stage that reads an epic's change folder — planner, architect,
dispatch, implementer, reviewer, qa, release and ops — SHALL check out the
first branch that **actually carries that epic's change folder**, in the
order: the epic branch, then the integration branch, then the default branch.

The fall-through is required, not advisory: an epic whose documents merged to
the default branch under the previous routing keeps its folder there, and a
stage that read only the branch the policy names would find no change folder
and fail on an epic that is otherwise healthy.

#### Scenario: a migrating epic is not stranded

- **WHEN** an `epics: false` epic's spec and design merged to the default
  branch before this change, and its implementer now runs
- **THEN** the implementer finds no change folder on the integration branch,
  falls through to the default branch, reads it there, and proceeds

#### Scenario: a new epic reads the integration branch

- **WHEN** an `epics: false` epic's documents merged to the integration
  branch under this change, and any later stage runs
- **THEN** that stage checks out the integration branch and reads the folder
  there, without consulting the default branch

### Requirement: Gate approval retargets toward the policy branch

At gate G1 and G2 approval, an open document PR whose base is not the branch
the policy names SHALL be retargeted onto it before being merged, so an epic
in flight adopts the current routing at its next gate. With `epics: true` the
target is the epic branch; with `epics: false` and an integration branch, the
target is the integration branch. A retarget preserves the PR, its reviews
and its head branch.

A document PR that has already merged SHALL NOT be rewritten or moved; that
epic finishes on the routing it started with, and the stage checkout
resolution above is what keeps it working.

#### Scenario: an in-flight epic adopts integration routing at its gate

- **WHEN** `epics: false`, an integration branch exists, and an open spec PR
  based on the default branch reaches gate G1 approval
- **THEN** the PR is retargeted onto the integration branch and squash-merged
  there, and the epic continues from that branch

#### Scenario: expedite opens the gate the same way

- **WHEN** the same epic carries `factory:expedite` and gate G1 approves
  itself
- **THEN** the retarget and merge are identical — the auto-approval path and
  the comment path share one routine — and nothing reaches the default branch
