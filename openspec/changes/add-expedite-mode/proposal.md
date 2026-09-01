# Add Expedite Mode (pipeline fast-track)

## Why

Once an epic's spec exists, every remaining step of the pipeline waits on a
human: gate G1 (spec), gate G2 (design), an `Approved` per task to start its
implementer, and a manual start for the Reviewer, QA and Release Manager on
every task (`factory:in-review`, `factory:in-test` and `factory:ready-to-ship`
"start nothing on their own" — handbook/next-step.json). For an epic the team
already trusts — a well-understood change, a repeat of a pattern the factory
has shipped before, work a maintainer would rubber-stamp at every gate — that
is five to twenty human touches that add latency and no judgement.

The existing fast lane (`factory:fast-track`) is not the answer: it skips the
pipeline entirely — no spec, no tasks, no design — and is deliberately limited
to changes too small to be worth the ceremony. What is missing is a way to keep
the ceremony (spec, design, per-task review and QA all still run) but waive the
*waiting*: a per-issue switch a human can flip at any step after the spec
exists, from which point the factory drives every remaining stage in sequence,
automatically, until the epic is fully assembled — and then stops, because
releasing to staging and promoting to production remain human decisions.

## What Changes

- **New orthogonal marker label `factory:expedite`** on an epic issue. Like
  `factory:blocked` it sits alongside the state label, is never a state itself,
  and may be applied or removed at any step. While present, every post-spec
  decision point that today waits for a human advances automatically. Applying
  it is itself gated: a new `expedite` approver list in
  `.github/factory-approvers.json` (empty ⇒ any owner/member/collaborator);
  an unauthorized application is reverted with a comment, exactly like a
  hand-applied gate label.
- **Auto-advance map** (only while the marker is present and the issue is not
  `factory:blocked`): `factory:spec-ready` auto-approves G1 (merge spec PR,
  flip, run Planner→Architect); `factory:design-ready` auto-approves G2 (merge
  design PRs, flip, run Dispatch); a task reaching `factory:ready` auto-starts
  its Implementer; `factory:in-review` auto-runs the Reviewer;
  `factory:in-test` auto-runs QA; `factory:ready-to-ship` auto-runs Release
  phase 1 (merge onto the epic branch → `factory:on-epic`). Reviewer rework
  rounds auto-restart the implementer inside the existing 2-round cap; task
  closes re-dispatch as today and newly-unblocked tasks auto-start.
- **The chain never touches staging or production.** Under `epics: true` it
  ends when the last task is `factory:on-epic`; under `epics: false` it ends
  with every task `factory:ready-to-ship` (there the Release role's very first
  merge would deploy staging, so it is not auto-run). Either way the epic then
  flips to a **new state `factory:epic-ready`**.
- **New human gate GS (staging release)** at `factory:epic-ready`: the epic is
  implemented, reviewed, tested and assembled as far as it can be without
  touching staging. A `staging` approver (new key; falls back to the `release`
  list) comments `Approved` on the epic — or uses the Console — and the
  Release Manager carries the epic to the integration branch and verifies it
  (`factory:in-staging`). Gate G3 (promotion to the default branch) is
  unchanged: a human merge in the GitHub UI, never comment-approvable.
  `factory:epic-ready` is **universal** — expedited or not — replacing the
  informal "start the Release Manager on the epic issue" step with an explicit,
  notified gate, so there is one state machine, not two.
- **Both engines, one decision table:** the LangGraph orchestrator chains
  roles in its `chain` node; the Actions engine chains by re-dispatching the
  pipeline workflow for the next role via `FACTORY_CROSS_REPO_TOKEN` (the
  workflow token cannot trigger runs). Without the PAT, expedite on the
  Actions engine degrades gracefully to a one-time comment and the normal
  human controls. New conformance fixtures pin every new routing branch;
  fixtures and both routers move in this one change.
- **Escape hatches:** removing the label stops auto-advance with no other
  effect; `factory:blocked` pauses it (a human reply resumes both, as today);
  `factory:in-progress` guards double-starts as today. Expedite never bypasses
  G0, GS or G3, never merges to the default branch, and is refused on release
  trackers, profile issues and `factory:fast-track` issues.
- **Surface updates:** FACTORY.md (§2a triggers, §3 states, §4 gates, new
  expedite section), `handbook/next-step.json` (a `factory:epic-ready` entry
  plus expedited wording variants), `scripts/setup-labels.sh` (two new
  labels), `templates/factory-approvers.json` (`expedite`, `staging`), the
  `release.md` / `dispatch.md` role prompts, and the Factory Console
  (companion change `add-expedite-mode-console` in software-factory-view:
  expedite toggle, badges, attention-queue suppression, GS gate panel).

## Capabilities

### New Capabilities

- `expedite/expedite-marker`: the `factory:expedite` label — semantics,
  authorization, scope, inheritance by task sub-issues, refusal cases, and
  removal.
- `expedite/auto-chaining`: the auto-advance map and its guards — which state
  advances to what, rework caps, engine mechanics, degradation without the
  PAT.
- `expedite/staging-gate`: the `factory:epic-ready` state and gate GS — who
  sets it, who approves it, what approval runs, and G3 unchanged.

### Modified Capabilities

- `branching/epic-promotion`: Release phase 2 (epic → integration) now starts
  from gate GS approval instead of being self-directed; the demotion path and
  G3 are unchanged.

## Impact

- **BREAKING (behavioral):** every epic now pauses at `factory:epic-ready`
  before the integration/staging merge, expedited or not. Operationally this
  formalizes a step a human already initiated by hand; epics currently sitting
  fully `factory:on-epic` should be flipped to `factory:epic-ready` once, by
  hand or by their next dispatch event.
- Repos re-run `scripts/setup-labels.sh` (23 → 25 labels) and optionally add
  the two approver keys; all other config is unchanged and the feature is
  opt-in per issue.
- Expedite's Actions-engine auto-chaining requires `FACTORY_CROSS_REPO_TOKEN`
  (already recommended for estates); the orchestrator engine needs nothing
  extra.
