# Delta: orchestration/engine-contract

## Purpose

Defines what any orchestration engine must do to drive the factory: routing
parity with the canonical decision table, the mandatory guards and traces,
role execution rules, and the security invariants — so a repo behaves
identically whichever engine moves its issues through the pipeline.

## ADDED Requirements

### Requirement: GitHub remains the sole source of factory state
An orchestration engine MUST treat GitHub (issues, sub-issues, `factory:*`
labels, milestones, PRs, comments) as the only authoritative record of
pipeline state, and OpenSpec change folders as the only authoritative record
of content. Any state an engine keeps internally (queues, checkpoints, run
history) SHALL be execution bookkeeping only: the engine MUST re-read GitHub
at the start of every role run and after every resume, and MUST NOT make a
routing decision from internal state that contradicts what GitHub shows.

#### Scenario: Engine restarts mid-pipeline
- **WHEN** an engine crashes or restarts while issues are mid-pipeline
- **THEN** after restart it reconstructs where every issue is from the
  issues' `factory:*` labels and comments alone
- **AND** resumes without duplicating a completed role run or skipping a
  pending one

#### Scenario: Human moves state while the engine is down
- **WHEN** a human flips a gate label while the engine is offline
- **THEN** on its next event or reconciliation pass the engine honours the
  label as it stands on GitHub, not a stale internal copy

### Requirement: Routing parity with the canonical decision table
Every engine SHALL implement the factory routing decision table — the mapping
from (GitHub event, issue kind, current `factory:*` labels, comment body,
sender authorization) to (role to run, issues to run it against, state
mutations, explanatory replies) — with decisions identical to the reference
implementation for the same inputs. This includes: intake on human-authored
issue open, release gating and parking in `factory:backlog`, tracker and
profile issue management, gate approvals (G0/G1/G2) with approver
enforcement, `Approved` on a ready task starting its implementer, blocked
resume on human reply, re-dispatch on task close, the fast lane, the
profiler triggers, and every "route nowhere but explain" branch.

#### Scenario: Identical route for identical input
- **WHEN** the same event payload, issue labels, and approver configuration
  are presented to two conforming engines
- **THEN** both choose the same role (or both route nowhere), target the
  same issue set, and make the same label mutations

#### Scenario: Conformance fixtures pass
- **WHEN** an engine's router is run against the shared conformance fixture
  suite (event + repo-state in, expected route + mutations + replies out)
- **THEN** every fixture passes, and the engine's CI fails if any fixture
  fails

#### Scenario: Unauthorized gate flip
- **WHEN** a user not on the gate's approver list applies a gate-approval
  label or comments `Approved` on a gated state
- **THEN** the engine reverts/ignores the flip and posts the same
  explanatory reply the reference router posts

### Requirement: Role runs are executed under the factory execution contract
For every role run, an engine MUST: assemble the prompt from the factory
handbook (FACTORY.md) plus the role prompt (`commands/<role>.md`) resolved
from a pinned factory ref, pass the target issue number as the role argument,
run the role with the factory tool allow-list and headless permission mode,
enforce a bounded turn budget and wall-clock timeout, and keep the factory's
own files outside the workspace an agent can commit from. Role prompts and
the handbook are the same bytes regardless of engine.

#### Scenario: Same role, same instructions
- **WHEN** the same role runs on the same issue under two different engines
  pinned to the same factory ref
- **THEN** the agent receives the same handbook and role instructions and
  the same operating rules (never push to main/master, never merge a PR,
  one role per run, agent-comment marker)

#### Scenario: Runaway role is bounded
- **WHEN** a role exceeds the engine's configured turn budget or timeout
- **THEN** the run is stopped, the failure is reported on the issue, and
  the in-progress marker is removed

### Requirement: Mandatory guards and traces
An engine SHALL apply the four factory guards on every role run: (1) the
**in-progress marker** — apply `factory:in-progress` when a role starts and
remove it when the run ends, whatever the outcome; (2) the **no-op guard** —
snapshot the issue's comment count and `factory:*` state before the role and
fail the run if neither a state label moved nor a comment was posted;
(3) the **failure report** — a failed run posts an explanatory comment on
its issue naming where to find the run log; (4) the **dead-comment reply** —
a comment that plainly requested something but routed nowhere receives an
explanatory reply. All engine- and agent-authored comments MUST end with the
`<!-- factory-agent -->` marker line so they never self-trigger.

#### Scenario: Silent run is failed
- **WHEN** a role run finishes without moving a state label or posting a
  comment
- **THEN** the engine marks that run failed and reports it, rather than
  reporting success

#### Scenario: Marker never outlives its run
- **WHEN** a role run ends by success, failure, timeout, or engine crash
  with recovery
- **THEN** `factory:in-progress` is removed from the issue

#### Scenario: Engine comments do not self-trigger
- **WHEN** an engine or agent posts a comment on a factory issue
- **THEN** the comment carries the agent marker and no engine routes it as
  a human comment

### Requirement: Security invariants are engine-independent
Regardless of engine: gate G3 (any merge into `main`/`master`, and staging →
production promotion) SHALL remain human-only; an engine MUST NOT merge PRs
or push to protected branches, and MUST run agents with the protected-branch
enforcement in place. Gate approvals SHALL be honoured only from the users
listed in `.github/factory-approvers.json` (or repo collaborators when a
list is empty). Credentials (Anthropic, GitHub) SHALL never appear in
issues, artifacts, PRs, or agent prompts. An engine SHALL act on GitHub with
credentials scoped to the repos it has claimed.

#### Scenario: Engine cannot merge to production
- **WHEN** any engine-run agent attempts to push to `main`/`master` or merge
  a pull request
- **THEN** the attempt is blocked and G3 still requires a human merge via
  the GitHub UI

#### Scenario: Approver list enforced identically
- **WHEN** `.github/factory-approvers.json` names approvers for a gate
- **THEN** the engine honours approvals only from those users, exactly as
  the reference router does

### Requirement: Per-repo configuration is read from the consuming repo
An engine SHALL read the consuming repo's factory configuration from the
same files the reference implementation reads — `.factory/profile.json`,
`.github/factory-models.json`, `.github/factory-approvers.json`,
`.github/factory-release.json` — at their current default-branch state, and
honour model preference chains by probing accessibility and selecting the
first accessible model, warning on each fallback and failing the run with a
clear error when a whole chain is inaccessible.

#### Scenario: Model chain degrades gracefully
- **WHEN** the first model in a role's preference chain is not accessible to
  the repo's credential
- **THEN** the engine records a warning and uses the next accessible model
  in the chain

#### Scenario: Config change needs no engine change
- **WHEN** a consuming repo edits its models, approvers, or release config
  and merges
- **THEN** the engine picks the change up on the next run with no engine
  redeployment
