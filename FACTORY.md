# The Software Factory

This is the **canonical conventions document** for an agent-driven delivery
pipeline: release → requirement issue → spec → tasks → design → code → review →
test → deploy → verification, with agents doing the work and humans holding the
gates.

How many gates is a per-epic decision (§4a); which of them can *never* be
delegated is not. Two are structural: **GS**, releasing an epic to staging, and
**G3**, promoting it to production. Everything before them is reviewable work
the factory may be trusted to carry; those two are the moments something leaves
the factory's own branches, and a human opens both.

It is repo-agnostic. Everything a role needs to know about a *particular*
codebase lives in that repo's `.factory/profile.json` (§2c) — never in these
prompts. An estate of N repositories runs N profiles and one copy of this
document.

**How it reaches your repos:** this file, the twelve role prompts, and the
protected-branch hook ship as the `factory` Claude Code plugin; the pipeline
ships as reusable GitHub Actions workflows. A consuming repo holds nine files,
none of them logic. See §10.

---

## 1. Two foundations, one rule

- **GitHub is the state machine.** Milestones are releases, issues and
  sub-issues are the work, labels encode *where* every piece of it is. Labels
  trigger agents.
- **OpenSpec is the content.** *What* is being built — proposal, WHEN/THEN
  requirement scenarios, technical design, task checklist — lives in
  `openspec/changes/<epic-issue-number>-<slug>/` in each affected repo.

**The rule: issues carry state plus a link to the change folder — never spec
content. Agents read requirements from the change folder, never from the issue
body.** This prevents the two-sources-of-truth drift.

## 2. Pipeline stages and agents

| # | Stage | Agent (role prompt) | Produces |
|---|---|---|---|
| 0 | Release | `/factory:scrum` | A release plan for one milestone — scope, sequencing, risks — and the gate-G0 hand-off that lets its issues start (§2d) |
| 1 | Intake | `/factory:intake` | `proposal.md` + `specs/` via `/opsx:explore` + `/opsx:propose`, opened as a PR |
| 2 | Plan | `/factory:planner` | `tasks.md` (≤ ~10 tasks, one PR each) mirrored into GitHub sub-issues; opens the shared design PR |
| 3 | Design | `/factory:architect` | `design.md` per affected repo (same branch/PR as `tasks.md` in the epic's repo); shared contract snippet identical across repos |
| 4 | Implement | `/factory:implementer` | Branch + commits + draft PR per task via `/opsx:apply` |
| 5 | Review | `/factory:reviewer` | Line-level review; approve or request changes |
| 6 | Test | `/factory:qa` | Scenario→test mapping, full suites green, test report on PR |
| 7 | Deploy | `/factory:release` | Dependency-ordered merges onto the **epic branch** (§6b), leaving the epic at `factory:epic-ready`; then, once a human opens gate GS, the integration PR onto the **integration branch** — or straight onto integration when the epic has no epic branch — staging verification, and the promotion PRs a human merges at gate G3 (§6a) |
| 8 | Verify | `/factory:ops` | Health/smoke checks, soak, `/opsx:archive`, issue closure |

Stage 0 is optional and off by default: with release gating disabled a filed
issue goes straight to Intake, which is how the factory behaved before §2d
existed.

Beside these stages runs one **fast lane**: `/factory:fasttrack` takes an issue
labelled `factory:fast-track` and produces a branch, a test and a
ready-for-review PR in a single run — no proposal, no `tasks.md`, no `design.md`
and no gate but G3. It is the whole pipeline for changes too small to be worth
the ceremony (§5). It skips the ceremony, not the staging step: its PR is based
on the integration branch (§6a) — the fast lane has no epic and so no epic
branch (§6b).

Cutting across the stages is one **switch**: `factory:expedite` (§4a) leaves
every stage above exactly as it is and removes the waiting between them, so a
trusted epic runs from approved spec to assembled epic without a human touch.
It is the opposite trade from the fast lane — all of the ceremony, none of the
pauses — and it too stops at the gates that put code on staging and in
production.

One more role sits outside the pipeline entirely: `/factory:profiler` writes and
maintains `.factory/profile.json` (§2c), the file the stage roles above depend
on. It is setup and upkeep, not delivery — it never touches an epic.

Role prompts are supplied by the `factory` plugin, so every repo runs the
**same twelve prompts** — there is no per-repo copy to drift. Stack-specific
knowledge lives in each repo's `.factory/profile.json` (§2c), which the
implementer, reviewer, qa, release and ops roles load at the start of every
run. In a multi-repo estate, nominate one **coordination repo** (the one that
owns the contract others consume) and file multi-repo epics there.

## 2a. Automation: the factory-pipeline workflow

`.github/workflows/factory-pipeline.yml` — a ~15-line caller stub in each repo
that invokes this repo's reusable workflow (§10) — wires the stages to GitHub
events, so **filing a plain issue is all a requester does**:

| Trigger | What runs |
|---|---|
| Any issue opened (human-authored, not `task(...)`, no factory state yet) | Auto-applies `factory:intake`, then runs the **Intake Analyst** — unless release gating is on (§2d), in which case the issue is parked in `factory:backlog` |
| A milestone is created, or an issue is added to one (release gating on) | A `release(<milestone>)` **tracker issue** is opened if the milestone has none |
| `factory:fast-track` applied (or an issue filed with it) | **Fast-Track** — implements the change, runs the repo's tests, and opens a PR for human review. No intake, spec, design or gates |
| An issue filed with `factory:profile`, or that label applied | **Profiler** — drafts or corrects `.factory/profile.json` from the code in your own runner and opens a PR (§2c) |
| A push to the default branch touching a manifest, lockfile, CI workflow or tool config | **Profiler** — re-verifies the profile against the new commit, opening a PR only where it disagrees (§2c) |
| Owner/collaborator comments exactly `Plan release` on a release tracker | **Scrum Master** — reads the whole milestone and posts the release plan |
| `factory:release-approved` on a tracker (gate G0) | Every `factory:backlog` issue in that milestone is moved to `factory:intake` and its **Intake Analyst** runs, all in the same run |
| Human applies `factory:spec-approved` (gate G1) | **Planner**, then **Architect** chained in the same run |
| Human applies `factory:design-approved` (gate G2) | **Dispatcher** — marks unblocked tasks `factory:ready` |
| `factory:expedite` applied to an epic (§4a) | Authorised against the `expedite` approvers, then the **auto-advance map** acts on whatever state the epic is already in: G1/G2 approve themselves, ready tasks start their implementers, and every later stage chains with no human start — up to gate GS, which it never opens |
| `factory:expedite` removed | Nothing runs. Auto-advance stops; the normal human controls resume from the current state, said once on the issue |
| A role finishes on an expedited issue | The engine starts the next role in the map (§4a) on the issue whose state that run just changed — the Actions engine by re-dispatching itself over `FACTORY_CROSS_REPO_TOKEN`, the orchestrator inside its own graph run |
| Owner/collaborator comments exactly `Approved` on an epic in `factory:epic-ready` (gate GS) | **Release Manager** phase 2 — the assembled epic is carried to the integration branch and verified there. Authorised against the `staging` approvers, falling back to `release` (§4) |
| `factory:in-staging` applied by the Release Manager | Nothing runs — the `release` approvers are assigned and @-mentioned to merge the promotion PRs. Gate G3 is a merge click, not a role (§6a) |
| Owner/collaborator comments exactly `Approved` on an issue in `factory:spec-ready` or `factory:design-ready` | The gate's document PR(s) in this repo are squash-merged, the label flips to the approved state, and the next stage (Planner→Architect, or Dispatcher) runs in the same workflow run. Strict match — "Approved, but..." is just a comment. G3 is deliberately not comment-approvable |
| The same comment on a release tracker in `factory:release-ready` | Gate G0 — the label flips to `factory:release-approved` and the milestone's issues are released (there is no document PR to merge) |
| Owner/collaborator comments exactly `Approved` on a task sub-issue in `factory:ready` | That task's **Implementer** starts. Not a gate — implementation had no trigger of its own; authorised against the `implementation` approver list. Declined while the task already carries `factory:in-progress`: the label stays `factory:ready` for the whole run, so a second `Approved` would put a second implementer on the same task and branch. The pipeline replies saying so and starts nothing |
| Any collaborator comments exactly `Review Done` on a task sub-issue in `factory:in-review` | The label flips straight to `factory:in-test`, skipping the Reviewer — for a human who reviewed the draft PR themselves. Like starting the Reviewer, there is no approver list for this stage. Declined while the task carries `factory:in-progress` (the Reviewer may be mid-run); no changes-requested equivalent — review the draft PR on GitHub if it needs work |
| A task sub-issue closes (its PR merged) while its epic is `factory:design-approved` | **Dispatcher** re-runs on the epic, releasing any task the merge just unblocked. Without this, tasks freed by a later merge sit with no `factory:*` label at all |
| Human replies on a `factory:blocked` issue | `factory:blocked` is cleared and the blocked stage re-runs, re-reading the whole thread (agent comments carry an `<!-- factory-agent -->` marker so they never self-trigger) |
| Actions → "Factory pipeline" → *Run workflow* | Any role on any issue/PR number (the manual/retry path; used for reviewer/qa/release/ops until those are event-wired) |

Every one of those runs ends by saying, on the issue, what is expected of the
next actor: which state the role left the issue in, who moves it from there,
and the exact control they use — a comment to type, a PR to merge, a Console
button, or a role to start. The wording is `handbook/next-step.json`, one
entry per `factory:*` state, rendered by both engines
(`scripts/say_next_step.py` for Actions, `factory_orchestrator.next_step` for
the orchestrator) so they cannot drift. It is said once per state: a task the
Reviewer sends back to `factory:ready` is announced again, a re-run that ends
where it started is not. This matters most for the states with no trigger of
their own — `factory:in-review`, `factory:in-test`, `factory:ready-to-ship`
are the pipeline waiting for a human to start the next role, and until the
notice existed nothing on the issue said so.

While any of those runs is actually executing a role, its issue carries
`factory:in-progress` — the pipeline applies it when the agent job starts and
removes it when the job ends, whatever the outcome. A role takes minutes, and
without the marker an issue being worked on right now looks exactly like one
nothing has started on; the only way to tell them apart was to open the Actions
tab. It is a marker, not a state: it sits alongside whatever `factory:*` state
the issue is in, no routing decision reads it as one, and no role should ever
add or remove it. One decision does consult it — the implementation start
above, because `factory:ready` stays on a task for the whole implementer run
and is therefore the one trigger a live run can be confused with. If a runner
dies hard enough that the cleanup step never runs, remove the label by hand:
until then the issue merely looks busy, except that an `Approved` on a ready
task will be declined.

### Events the factory itself raises

Some of that work reaches the factory wearing the factory's own name. A role
that hits a defect too big to fix inside its own issue files the fix as a
separate `factory:fast-track` issue; release trackers are opened by the
pipeline. Those are human-initiated requests — a person asked for them, an
agent typed them — so the triggering actor is the factory's GitHub App rather
than a person.

`claude-code-action` refuses to run for a non-human actor unless that bot is
listed in its `allowed_bots` input, so the reusable workflow passes one:
**`allowed_bots`, defaulting to `claude`** — the factory's own App and nothing
else. Override it in the caller stub only if your factory runs under a
differently-named App. `*` allows every bot; on a public repo that hands any
App able to label an issue a prompt-controlled agent run, so do not.

Authorship is not what keeps the pipeline safe, and the router never relied on
it: a bot-authored issue still does not enter intake when it is opened, agent
comments carry `<!-- factory-agent -->` so they cannot self-trigger, and a gate
flip is checked against `.github/factory-approvers.json` no matter who sends
it. What the actor check added on top of that was a run that died at
`Workflow initiated by non-human actor` — the request stranded on a red run,
with nothing on the issue to say why.

Prerequisites (per repo):
- **Secret** `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN` from
  `claude setup-token` for Claude subscription billing) in Settings → Secrets
  and variables → Actions. The workflow fails with a clear message if missing.
- **Secret** `FACTORY_CROSS_REPO_TOKEN` (recommended; required for multi-repo
  epics run from Actions): a fine-grained PAT covering every repo in the
  estate, with read/write on **Issues, Contents and Pull requests**
  (github.com/settings/personal-access-tokens). With it, the Planner can
  create sub-issues in sibling repos, the Architect can push design.md there,
  and agent label flips emit real events so cross-repo stages chain
  automatically. Without it, agents fall back to the single-repo workflow
  token and will apply `factory:blocked` when an epic needs cross-repo access.
- The workflow must exist on the **default branch** before GitHub will fire it.

### Model routing (which Claude model runs each stage)

`.github/factory-models.json` in the consuming repo maps each role to a
**preference chain** — a list of models in order. Before launching an agent,
the workflow probes each model with a one-token ping and uses the first one
the repo's credential can actually access, so a plan/tier gap degrades
gracefully instead of failing the run. Missing roles fall back to
`claude-sonnet-5`. Current profile:

| Stages | Preference chain | Why |
|---|---|---|
| scrum, intake, planner, architect, reviewer | `claude-fable-5` → `claude-opus-5` → `claude-sonnet-5` | Errors here compound downstream: a wrong release scope, spec, plan or design — or a missed review defect — costs far more than the model delta |
| implementer, qa, release | `claude-opus-5` → `claude-sonnet-5` | Strong coding/testing quality on the volume stages, guardrailed by the merged design.md and spec scenarios |
| dispatch, ops | `claude-haiku-4-5-20251001` → `claude-sonnet-5` | Mechanical label routing and health-check verification |
| profiler | `claude-opus-5` → `claude-sonnet-5` | Reads a whole unfamiliar codebase and writes what every other role then treats as true |

To retune: edit the JSON, merge — next runs pick it up. A `::warning::` line
in the run log shows every fallback taken; if the whole chain is inaccessible
the run fails with a clear error.

Two operational notes:
- With the default token, label changes made *by* a run don't emit trigger
  events (GitHub anti-recursion); with the PAT they do. `factory:planned` is
  deliberately unmapped so the in-run planner→architect chain never
  double-fires the Architect in either mode.
- Re-running a stage: remove and re-add the trigger label (human flips fire
  events), or use the *Run workflow* button (any role, any issue number).

## 2c. Repo profiles (stack knowledge as data, not prose)

`.factory/profile.json` at each repo's root is the authoritative source for
that repo's stack facts. Role prompts stay generic; only this file differs
between repos. A missing/unparseable profile hard-blocks the per-repo roles
(`factory:blocked`) rather than letting them guess.

| Field | Consumed by | Contents |
|---|---|---|
| `estate_role` | planner, release | Where this repo sits among its siblings — the source of cross-repo merge order |
| `stack` | implementer, architect | Languages, frameworks, major libraries |
| `branches` | implementer, fasttrack, reviewer, qa, release | `default` + `staging`, the integration branch (§6a). `staging` is null unless THIS repo's branch is named differently from the org's policy file |
| `commands` | implementer, qa | `test` / `build` / `lint` — null means "this repo has no such gate" |
| `conventions` | implementer, architect | The patterns code must follow |
| `review_checklist` | reviewer | Repo-specific review points beyond the generic security/conformance checks |
| `qa_notes` | qa, implementer | How tests are written and run here (fixtures, mocks, e2e guidance) |
| `gotchas` | implementer, reviewer, qa | Pre-existing failures, judge-the-delta rules, things never to weaken |
| `reuse_hotspots` | reviewer | Where duplicated code most likely already exists |
| `deploy` | release, ops | `health_checks` (runnable commands, not descriptions) and `notes` (failures that halt a release train) |

Schema: `templates/profile.schema.json`. Worked example:
`templates/profile.example.json`.

To change how the factory codes in a repo, edit its profile — not the prompts.
This is also what makes the factory portable: pointing it at a new project is
writing one profile, not rewriting twelve prompts.

### Who writes it

The **Profiler** (`commands/profiler.md`), on an issue labelled
`factory:profile`. It is the only role that does not read the profile first —
it is the one that writes it. It runs in the repo's own Actions runner, where
the code already is, so nothing outside the repo has to read the source to
produce a profile.

It records only what it verified in that run: every command in `commands` is a
command it executed, a suite that fails on a clean checkout becomes a `gotcha`
rather than a silence, and the PR body cites the evidence field by field. It
proposes; a human merges. That merge is where the repo's owner agrees to what
the factory will treat as true from then on.

| Trigger | What it does |
|---|---|
| An issue filed with `factory:profile` (the Factory Console's profile step files it for you), or the label re-applied | Draft the profile, or correct the one that is there |
| A push to the default branch touching a manifest, lockfile, CI workflow or tool config — the `paths:` list in the caller stub | Re-verify it against the new commit |

Both land on the same singleton issue, so what the factory believes about this
repo — and how that changed — reads in one thread. A run that finds nothing to
change says so in one comment and opens no PR: a maintenance check that PRs on
every push gets muted, and then it protects nothing.

## 2b. Approvers and notifications

`.github/factory-approvers.json` in the consuming repo maps each gate to
the GitHub usernames responsible for it:

| Key | Responsibility | Notified when | How they act |
|---|---|---|---|
| `spec` | Gate G1 — approve the spec PR | Issue reaches `factory:spec-ready` | Merge the PR + apply the label, or comment `Approved` |
| `design` | Gate G2 — approve the plan+design PR | Issue reaches `factory:design-ready` | Same |
| `implementation` | Start implementers on ready tasks | A task reaches `factory:ready` | Comment `Approved` on the task, or Run workflow (role: implementer) |
| `expedite` | Who may put an epic on the fast path (§4a) | — (it is applied, not awaited) | Apply `factory:expedite` to the epic. This pre-approves G1, G2 and every implementation start, which is why applying it is itself authorised |
| `staging` | Gate GS — release the assembled epic to staging | Epic reaches `factory:epic-ready` | Comment `Approved` on the epic. Falls back to the `release` list when the key is absent |
| `release` | Gate G3 — production go | Issue reaches `factory:in-staging` and the Release Manager posts the merge list | Merge the promotion PRs (integration → default branch) in the posted order |

Mechanics:
- **Notification** = GitHub-native: the pipeline assigns the issue to the
  gate's approvers and posts an @-mention comment (email/app push follows each
  user's own GitHub notification settings). Agents also cc the approvers in
  their hand-off comments.
- **Enforcement** = router-side: an `Approved` comment or a gate-label flip is
  honored only from that gate's listed users; unauthorized flips are reverted
  with an explanatory comment. An empty list means any owner/member/
  collaborator may approve.
- Edit the JSON and merge to change who owns a gate; approvers must be
  repo collaborators to be assignable and to act.

## 2d. Releases: milestone gating and gate G0

Without gating, filing an issue starts an agent. That is the right default for a
repo with a handful of requirements a month and the wrong one for a team that
plans in releases: work enters one issue at a time, in the order it was typed,
and nobody ever looks at the set.

**A release is a GitHub milestone.** Turn gating on and a filed requirement is
parked in `factory:backlog` — no agent touches it — until the milestone it
belongs to is approved. Approving a release starts *every* issue in it at once.

`.github/factory-release.json` in the consuming repo:

| Key | Values | Meaning |
|---|---|---|
| `gating` | `"milestone"` / `"none"` | `"none"` (also: file absent) is the pre-release behaviour — a filed issue goes straight to intake |
| `approval` | `"human"` / `"agent"` | Who opens gate G0: a `release_scope` approver, or the Scrum Master's own GO verdict |
| `auto_create_release_issue` | `true` / `false` | Open a `release(<milestone>)` tracker automatically for each milestone |
| `exempt_labels` | list, default `["factory:fast-track"]` | Issues carrying any of these skip the release queue entirely |

### How a release runs

1. **Create the milestone.** The pipeline opens a tracker issue titled
   `release(<milestone-number>): <name>`, labelled `factory:release` (a *kind*
   marker, not a state) plus `factory:release-planning`. It is the release's
   thread: where the plan is posted and where G0 is opened. The tracker is
   bot-opened, so nobody is subscribed to it — its body cc's the `release_scope`
   approvers and says outright that nothing runs until one of them acts.
2. **File issues against it.** Each is parked in `factory:backlog` with a
   comment naming its release tracker and the two commands that move it
   (`Plan release`, then `Approved`). An issue filed with no milestone is parked
   too, with no release at all — setting the milestone later queues it and posts
   that same pointer, once per tracker.
3. **`Plan release`.** Comment exactly that on the tracker and the **Scrum
   Master** reads every issue in the milestone and posts one release plan:
   scope table, sequencing between issues, risks, oversized or duplicate items,
   what it recommends dropping, and a GO/NO-GO verdict. It moves the tracker to
   `factory:release-ready`.
4. **Gate G0.** A `release_scope` approver comments exactly `Approved` on the
   tracker (or applies `factory:release-approved` by hand). Every
   `factory:backlog` issue in the milestone flips to `factory:intake` and its
   Intake Analyst runs — in one workflow run, as a job matrix, four at a time.
   The tracker gets a receipt comment listing what started and what was left
   alone. From then on, an issue *added* to that milestone enters intake
   immediately.

In `"approval": "agent"` mode step 4 has no human in it: the Scrum Master's GO
applies `factory:release-approved` itself and the same batch release follows in
that run. A NO-GO applies `factory:blocked` and says what has to change. The
mode exists because release scope is the one gate whose input — the set of
issues — the agent can read completely; use it when the cost of a wrong batch is
low, and leave it on `"human"` when it is not.

### What gating deliberately does not do

- **It does not stop work already in flight.** Removing an issue from a
  milestone parks it only if it has not passed intake; past that, the release
  label is bookkeeping and the pipeline carries on.
- **It does not gate sub-issues.** `task(...)` issues are created by the Planner
  downstream of G1 and are never parked.
- **It does not cross repos.** Milestones are per-repo, so a multi-repo epic is
  gated in the repo where its epic issue is filed; the sub-issues the Planner
  opens in sibling repos are unaffected.
- **It is not a deadline.** The milestone's due date and its `closed` state mean
  nothing to the factory; only the tracker's label does.

## 2e. Orchestration engines (which motor drives the pipeline)

GitHub is the state machine and OpenSpec is the content; the *engine* is
only the motor that reads events and turns them into agent runs. Two engines
implement the same routing decision table — pinned by the shared conformance
fixtures in `orchestrator/conformance/` — and a repo picks one in
`.github/factory-orchestrator.json`:

| `engine` | What drives the repo |
|---|---|
| `github-actions` (default; also: file absent or unparseable) | The reusable workflow in §2a — zero infrastructure, exactly the behaviour documented above |
| `langgraph` | The LangGraph orchestrator (`orchestrator/`): a long-lived service receiving GitHub App webhooks, routing with a Python port of the router, and running roles as headless Claude Code in isolated workspaces |

Exactly one engine acts on a repo at a time. When the file names an external
engine, the Actions route job stands down before any side effect (a log line
says which engine holds the claim), and the external engine refuses events
for repos whose config does not name it — both checks evaluate the same file
at processing time, so a config race resolves to at most one engine per
event. Because all pipeline state lives on GitHub, switching engines is a
one-file PR in either direction with no state migration: issues continue
from their current labels under the new engine. Labels, gates, approvers,
role prompts and every trace convention are identical whichever engine runs
— the Console cannot tell them apart. Deployment and migration runbook:
`orchestrator/README.md`.

## 3. Label state machine

State labels are mutually exclusive; exactly one `factory:*` state label per
issue at a time. Five labels are not states and sit alongside one:
`factory:release` (a *kind* marker identifying a release tracker, which also
carries one `factory:release-*` state), `factory:profile` (a *kind* marker
identifying the repo's profile issue, §2c), `factory:in-progress` (a run is live
on this issue right now), `factory:expedite` (this epic advances itself, §4a)
and `factory:blocked` (halted, whatever the state).
Create them with `scripts/setup-labels.sh`.

| Label | Meaning | Set by | Advanced by |
|---|---|---|---|
| `factory:backlog` | Filed, not yet in an approved release (§2d) | Pipeline, on `issues.opened` | Gate G0 → `factory:intake` |
| `factory:release` | *Kind:* this issue tracks a release milestone | Pipeline, with the tracker | — (never removed) |
| `factory:release-planning` | Awaiting `Plan release` — **nothing is running** | Pipeline, with the tracker | Scrum Master → `factory:release-ready` |
| `factory:release-ready` | Release plan posted, awaiting **gate G0** | Scrum Master | Human (G0) → `factory:release-approved` |
| `factory:release-approved` | Released; its issues are in the pipeline | Human (G0), or Scrum Master in agent mode | — (terminal for the tracker) |
| `factory:intake` | New requirement awaiting analysis | Issue template, pipeline, or gate G0 | Intake → `factory:spec-ready` |
| `factory:spec-ready` | Spec PR open, awaiting **gate G1** | Intake | Human merges spec PR → `factory:spec-approved` |
| `factory:spec-approved` | Released for planning | Human (G1) | Planner → `factory:planned` |
| `factory:planned` | tasks.md + sub-issues created | Planner | Architect → `factory:design-ready` |
| `factory:design-ready` | design.md PR(s) open, awaiting **gate G2** | Architect | Human merges design PR → `factory:design-approved` |
| `factory:design-approved` | Released for implementation | Human (G2) | Orchestrator → `factory:ready` on unblocked tasks |
| `factory:ready` | Task unblocked; implementer may start | Orchestrator | Implementer → `factory:in-review` |
| `factory:in-review` | Draft PR under agent review | Implementer | Reviewer → `factory:in-test` (or back to `factory:ready`), or a human comments `Review Done` → `factory:in-test` directly |
| `factory:in-test` | QA verifying scenarios | Reviewer | QA → `factory:ready-to-ship` |
| `factory:ready-to-ship` | Green; awaiting the merge onto the epic branch (§6b), or onto the staging branch when the epic has no epic branch (§6a) | QA | Release → `factory:on-epic` (or `factory:in-staging`) |
| `factory:on-epic` | Merged onto the epic branch and green there; awaiting the rest of the epic (§6b). Only with `epics: true` | Release | The epic's last task lands → the **epic** goes `factory:epic-ready` |
| `factory:epic-ready` | *On the epic:* every task is assembled and green, and nothing has touched staging yet. Awaiting **gate GS** | Release, or Dispatch on a re-run that finds the epic complete | Human (GS) → Release carries the epic to integration → `factory:in-staging` |
| `factory:in-staging` | On the integration branch and verified there; promotion PR open, awaiting **gate G3** | Release | Human merges the promotion PR → `factory:deployed` |
| `factory:deployed` | In production, soak in progress | Release | Ops archives + closes, or files `factory:incident` |
| `factory:fast-track` | *Kind:* small change, handled by the fast lane instead of the pipeline | Human triage, or the Scrum Master recommending it | Fast-Track opens a PR → human review + merge |
| `factory:profile` | *Kind:* this issue is the home of `.factory/profile.json` (§2c) | Factory Console's profile step, or a human | Profiler removes it when it finishes; re-apply to re-run |
| `factory:expedite` | *Marker:* this epic advances itself — every stage after the spec runs without waiting for a human, up to gate GS (§4a) | Human triage, authorised against the `expedite` approvers | Human removes it; the normal gates resume from the current state |
| `factory:in-progress` | *Marker:* a factory agent run is live on this issue right now | Pipeline, when an agent job starts | Pipeline, when that job ends (always, including failure and timeout) |
| `factory:blocked` | Needs human attention | Any agent | Human |
| `factory:incident` | Post-deploy regression | Ops Monitor | Human + Release (rollback) |

## 4. Human gates

- **G0 — Release approval (only with gating on, §2d):** read the Scrum Master's
  release plan on the tracker issue, then comment `Approved` on it (or apply
  `factory:release-approved`). Every `factory:backlog` issue in the milestone
  enters intake. This is the one gate that can be delegated to an agent, by
  setting `"approval": "agent"` in `.github/factory-release.json`.
- **G1 — Spec approval:** review the `proposal.md` + `specs/` PR, then either
  merge it and apply `factory:spec-approved`, or simply comment `Approved` on
  the epic (the pipeline merges the PR and flips the label for you).
- **G2 — Design approval:** review the design PR(s) — one per affected repo;
  in the epic's repo it carries both `tasks.md` and `design.md` — then either
  merge and apply `factory:design-approved`, or comment `Approved` on the epic.
  Note: comment approval merges the design PR in the epic's repo; sibling-repo
  design PRs still need their own merge.
- **GS — Release to staging:** the epic is at `factory:epic-ready` — every task
  implemented, reviewed, tested and assembled, and nothing of it on staging yet
  (§6b). A `staging` approver (falling back to the `release` list) comments
  exactly `Approved` on the epic, and the Release Manager carries the whole
  epic to the integration branch and verifies it there. This is the gate an
  expedited epic (§4a) stops at: the auto-advance map never opens it.
- **G3 — Promotion to the default branch:** every PR into `main` is merged
  **by a human via the GitHub UI** — never by an agent. By the time a human
  sees one, the change is already merged onto the integration branch and proved
  there (§6a), so the only PR that ever reaches `main` is a promotion PR from
  that branch, carrying the staging evidence in its body. GitHub branch
  protection is not available on the current plan, so this is enforced
  factory-side (see §8a): agents are hard-blocked from pushing to `main` and
  from using PR-merge tools. The merge button *is* the gate.

**Epic assembly** — merging each green task PR onto the epic branch (§6b) in
dependency order, running the repo's checks after each one — is deliberately
*not* a gate. It costs a human nothing and it is what makes the later gates
decisions about a proven build rather than hopeful ones. Its state is
`factory:on-epic` (§3), and it ends at `factory:epic-ready`.

Leaving the epic branch *is* a gate, and that is GS. The epic → integration
merge deploys staging, so a human says when: one approval per epic, at the
moment the whole epic is assembled and green, rather than a start button per
task. (Before this state existed, a human started the Release Manager's
second phase by hand with nothing on the issue asking them to; GS is that same
click, now notified, authorised and recorded.) Under `epics: false` there is
no epic branch to leave, so GS is where the task PRs merge onto the
integration branch instead — the gate means the same thing either way:
*approving this puts the epic on staging*.

Everything else runs unattended. Any human may take over any stage at any time
by doing the work manually and setting the next label.

## 4a. Expedite: the epic that advances itself

Gates G1 and G2 and every start button between them exist because somebody
wants to look. For an epic nobody intends to look at — a well-understood
change, the fifth repeat of a pattern, work a maintainer would rubber-stamp at
every step — they are five to twenty touches that add latency and no judgement.

`factory:expedite` is a **marker** on an epic (§3), applied by a human at any
step, that waives the *waiting* without waiving the *work*: the spec is still
written, the design is still written, every task is still reviewed and tested.
Only the pauses go.

It is not the fast lane. `factory:fast-track` (§5) skips the ceremony for a
change too small to deserve it and produces no spec, no tasks and no design.
Expedite keeps all of it and runs it end to end. The two labels are refused on
each other's issues.

### What it advances

While the marker is on the epic and the issue is not `factory:blocked`:

| The issue is at | What happens instead of waiting |
|---|---|
| epic `factory:spec-ready` | **Gate G1 approves itself** — the spec PR merges, the epic flips to `factory:spec-approved`, the Planner runs (chaining the Architect as always) |
| epic `factory:design-ready` | **Gate G2 approves itself** — the design PR(s) merge, the epic flips to `factory:design-approved`, the Dispatcher runs |
| task `factory:ready` | Its Implementer starts, with no `Approved` comment |
| task `factory:in-review` | The Reviewer runs |
| task `factory:in-test` | QA runs |
| task `factory:ready-to-ship` | With `epics: true`, Release phase 1 merges it onto the epic branch (`factory:on-epic`). With `epics: false`, **nothing** — see below |
| the epic's last task lands | The epic flips to `factory:epic-ready` and **the chain ends** |

The map is read the same way whether a state was just *reached* by a role
finishing or was already there when the marker was *applied*: expediting an
epic that has been sitting at `factory:design-ready` for a week starts it
moving immediately.

### What it never touches

- **Gate G0** (release scope) is upstream of the spec and unaffected: an
  expedited issue still waits for its milestone. Applied before a spec exists,
  the marker is simply dormant — it is not refused, and its first act is the
  G1 approval whenever intake gets there.
- **Gate GS** (release to staging) is where the chain stops, always.
- **Gate G3** (production) is unchanged in every respect: a human merging a
  promotion PR in the GitHub UI, never comment-approvable, never an agent.

**One thing it does merge, and you should know it.** Approving G1 and G2
squash-merges the spec and design PRs, and under `epics: false` those PRs
base on the **default branch** (§6) — so on that policy, expedite lets
document PRs reach `main` with no per-gate click. That is not a hole in §8a:
those merges are documents-only, the deploy workflows `paths-ignore` them,
and the branch guard classifies them as such. It is the switch working as
intended — the click moved from each gate to the moment somebody applied the
marker, which is why applying it is authorised (§2b). Under `epics: true`
they merge to the epic branch instead and never touch `main` before
promotion. No *code* reaches `main` either way except through gate G3.

Beyond that, nothing auto-advanced ever merges to the integration branch or
the default branch. That is why `epics: false` stops the chain at
`factory:ready-to-ship`: with no epic branch, the Release Manager's *first*
merge is onto the integration branch, and that merge is the staging deploy.
Under `epics: true` phase 1 merges onto the epic branch, which is the factory's
own scratch space, so the chain runs it. Either way the epic ends at
`factory:epic-ready` and a human opens GS.

### Scope, inheritance and refusals

The marker lives on the **epic**. Task sub-issues are expedited exactly when
their epic carries it right now, resolved through the task's `task(<epic>)`
title and its `Part of <owner>/<repo>#<n>` marker — the same resolution, and
the same cross-repo `FACTORY_CROSS_REPO_TOKEN` requirement, as the re-dispatch
on task close (§7). The label is deliberately **not** copied onto tasks: a copy
drifts the moment somebody takes expedite off the epic.

Applying it is authorised against the `expedite` approvers (§2b), because
applying it *is* the G1 and G2 approval. An unauthorised application is
reverted with a comment, exactly like a hand-applied gate label. Removing it
is unrestricted — removal only puts humans back in the loop, which is always
safe.

It is refused, with a comment, on release trackers, on the profile issue, and
on `factory:fast-track` issues (that lane has no pre-G3 gate to waive).

### Stopping it

- **Remove the label.** Auto-advance stops; runs already live finish normally;
  no state changes. The pipeline continues under the normal gates from
  wherever each issue stands, and the factory says so once on the issue.
- **`factory:blocked`** pauses it exactly as it pauses everything else. A human
  reply clears the label, re-runs the halted stage, and the chain resumes with
  it if the marker is still on.
- **The rework cap** is unchanged: the Reviewer sending a task back is the
  map's only loop, and the existing two-round limit (§8) ends it in
  `factory:blocked` rather than a third automatic implementer.
- **`factory:in-progress`** guards every auto-start exactly as it guards a
  human `Approved`, so a chained run can never double up on a live one.

### The engines

Both engines run the map from one decision table, pinned by the shared
conformance fixtures (§2e) — as always, behaviour and fixtures move together.
They execute it differently because their event models differ:

- **The orchestrator** appends follow-ups inside the graph run it is already
  in, the way it already fans a release out.
- **The Actions engine** re-dispatches itself: one `workflow_dispatch` per
  follow-up issue, so each role gets its own run, its own timeout and its own
  model resolution. That needs **`FACTORY_CROSS_REPO_TOKEN`** — the workflow
  token cannot start workflows (§2a). Without the PAT the chain cannot run at
  all, so it says so once on the issue and names the manual control; the run
  ends green and nothing stalls silently.

## 5. OpenSpec conventions

- **Change naming:** `openspec/changes/<epic-issue-number>-<slug>/`
  (e.g. `openspec/changes/123-payment-reminders/`).
- **Scope:** one change per epic, **max ~10 tasks**. The Planner splits larger
  epics into sequential changes.
- **Fast-track bypass:** bug fixes and trivial tweaks skip OpenSpec entirely —
  label `factory:fast-track` and the **Fast-Track** role implements the change,
  runs the repo's test and build commands, and opens a ready-for-review PR in
  one run. No change folder, no sub-issues, no G1/G2; the human merge (G3) is
  the only gate left. The role sizes the issue before writing any code and
  hands it back to the normal pipeline — removing the label, saying why — when
  it needs a migration, a new dependency, a new public contract, or a design
  decision worth arguing separately. Its PR is based on the integration branch
  (§6a) — merging it puts the change on staging, not in production; the
  promotion PR still carries it to the default branch. `factory:expedite`
  (§4a) is refused on a fast-track issue: this lane has no pre-G3 gate to
  waive, so the two labels never sit together.
- **Commands (OpenSpec v1.7 core profile):** `/opsx:explore`, `/opsx:propose`,
  `/opsx:apply`, `/opsx:update`, `/opsx:sync`, `/opsx:archive`.
- **Archive:** only the Ops Monitor archives, and only after production soak
  passes. Durable requirements accumulate in `openspec/specs/`.
- **Telemetry:** disabled — set `OPENSPEC_TELEMETRY=0` in agent environments.

## 6. Branching and PRs

- Epic branch (only with `epics: true`, §6b): `factory/epic-<epic-issue>`,
  cut from the repo's default branch at intake. It is the epic's home: every
  spec, design and task PR of that epic merges into it first.
- Spec branch: `factory/<epic-issue>-spec`; shared plan+design branch:
  `factory/<epic-issue>-design` (carries `tasks.md` + `design.md` in the
  epic's repo; `design.md` only in sibling repos). With `epics: true` both
  are cut from the epic branch; otherwise from the default branch.
- Task branches: `factory/<task-issue-number>-<slug>` cut from the epic
  branch (§6b) when the epic has one, else from the repo's **integration
  branch** (§6a) — cutting from the default branch produces a diff against a
  base that is missing everything already merged ahead of it.
- One task = one PR. PR body links its task issue (`Closes #N`) and the change
  folder, and notes any deviation from `design.md`.
- Draft PR until the Reviewer marks it ready. CI must be green before
  `factory:ready-to-ship`.

### Where PRs merge (base branches)

With `epics: true` (§6b), for every epic-pipeline PR:

- **Document PRs (spec, plan+design):** into the **epic branch**. Gate G1/G2
  approval squash-merges them there, so the approved change folder lives on
  the epic branch — where every later stage of that epic reads it — and
  reaches the default branch with the code, via staging, in the promotion
  merge. Documents and code travel as one unit.
- **Task PRs:** into the **epic branch**, merged by the Release Manager in
  dependency order (§6b). A task PR based on the default or integration
  branch is a blocking review finding.
- **Integration PR:** one epic-branch → integration-branch PR per repo, opened
  and merged by the Release Manager once the epic is complete and green on its
  branch. Merging it puts the whole epic on staging — the release train
  assembling.
- **Production promotion (gate G3):** unchanged — one
  integration → default-branch PR per repo, merged by a human.

Under `epics: false` (and always, for the PR kinds below):

- **Implementation PRs — task PRs and fast-lane PRs alike:** into the repo's
  **integration branch** (§6a), never the default branch. Merging there
  auto-deploys the staging environment — that's the release train assembling,
  and the change being proved before anyone is asked to ship it. Fast-lane
  PRs take this route under either policy: the fast lane has no epic and no
  epic branch.
- **Production promotion (gate G3):** one integration → default-branch PR per
  repo, merged by a human in the Release Manager's posted order. That merge is
  the production deploy, and it is the **only** kind of PR that ever targets
  the default branch.
- **Document PRs (spec, plan+design, profile) under `epics: false`** — and
  profile PRs always, having no epic: into the repo's **default branch**
  directly. They are not changes to the product: the deploy workflows
  `paths-ignore` the factory/document paths (`openspec/**`, `docs/**`,
  `FACTORY.md`, `.claude/**`, factory workflow files), so a docs-only merge
  deploys nothing, and there is nothing for a staging environment to prove
  about them. Routing them through integration would actively break the
  pipeline: every later stage of a no-epic-branch epic clones the *default*
  branch, so an approved spec parked on the integration branch would be
  invisible to the planner, the architect and every implementer until the
  next release promoted it. Gates G1 and G2 are those PRs' review. (With
  `epics: true` the same two halves move together: documents merge to the
  epic branch *and* stages read from it — §6b.)
- During the pre-merge pilot, all PRs base on the factory development branch
  instead.

## 6a. The integration branch (staging first, always)

**Nothing the factory writes reaches the default branch without being merged
to, and proved on, an integration branch first.** That branch is the org's —
`staging`, `develop`, `qa`, `integration`, whatever the estate already calls
it. The name is arbitrary; the step is not.

The policy lives in `.github/factory-branches.json`, copied from
`templates/factory-branches.json` and **identical across the estate** — it is
an org decision, not a per-repo one:

```json
{ "staging": "staging", "required": true, "auto_create": true, "epics": true }
```

| Key | Meaning |
|---|---|
| `staging` | The org's integration branch name. Absent file ⇒ `"staging"` |
| `required` | `true` (default): an implementation PR may never be based on the default branch. `false`: the pre-policy fallback — integration where a profile names one, default branch elsewhere |
| `auto_create` | `true` (default): the branch is cut from the default branch the first time it is needed, so adopting the policy costs no manual setup. `false`: a missing branch blocks the run instead |
| `epics` | `true`: every epic gets a dedicated `factory/epic-<n>` branch that all of its artifacts merge into first (§6b). `false` (the default, and the absent-file/absent-key value): the pre-epic behaviour above |

**Resolving the branch for a repo,** which the implementer, fast-track,
reviewer, qa and release roles all do at step 0a:

1. The repo's `.factory/profile.json` `branches.staging`, when that is a
   non-null string. This overrides **the name only** — for a repo whose branch
   is genuinely called something else — never whether the step runs.
2. Otherwise the policy file's `staging`.
3. Otherwise `"staging"`.

Two sources, no ambiguity: the policy file says *whether* and *what the org
calls it*; the profile says *what this repo calls it* when that differs.

**What it buys.** Every change is deployed and health-checked on staging
before a human is asked to approve anything, so gate G3 stops being a judgement
about a diff and becomes a decision about a build that already ran. A broken
change is caught on a branch the factory may write to, and fixed there, instead
of on the branch it may not. And an epic's PRs land as one train: the whole set
is integrated and green together, or none of it is promoted.

**The cost, stated plainly.** The integration branch is a real branch that
drifts from the default branch between releases. When a promotion PR conflicts,
the fix is to merge the default branch *into* integration and re-verify staging
— never to rewrite integration's history and never to resolve it on the default
branch side. Long-lived integration branches rot if releases are rare; promote
often.

## 6b. The epic branch (each epic isolated, testable on its own)

With `epics: true` in the policy file (§6a), each epic gets **one branch that
holds everything the epic produces**: `factory/epic-<epic-issue-number>`, cut
from the repo's **default branch** the first time the epic needs it — at
intake, before the spec PR opens (creating it when it already exists is a
no-op). For a cross-repo epic the number is the epic issue's number in the
coordination repo, so the branch name is identical in every affected repo.

**What routes through it.** The spec PR, the plan+design PR and every task PR
of the epic base on the epic branch (§6); every post-intake stage of the epic
— planner, architect, implementer, reviewer, qa, release phase 1, ops — checks
out the epic branch, because the approved change folder lives there and
nowhere else until promotion. The Release Manager assembles the epic's task
PRs onto it in dependency order, verifying after each merge (and against a
per-epic preview environment when the repo profile defines one). Tasks merged
and green there carry `factory:on-epic` (§3).

**Why cut from the default branch, not staging.** Cutting from staging would
leak every other in-flight epic into this epic's test surface. Cut from the
released baseline, each epic is provable on its own; the reconciliation with
staging is paid exactly once, at the integration PR. To keep parallel epics
from rotting, after any promotion PR merges, the default branch is merged
*into* every live epic branch (a merge, never a rebase — epic branch history
is never rewritten). A refresh conflict marks the epic `factory:blocked` with
the conflicting files named; it is resolved on the epic branch, never
silently.

**Leaving the epic branch.** When every task is `factory:on-epic` and the
epic branch's full suite is green, the epic goes to `factory:epic-ready` and
waits: this is **gate GS** (§4), the one human decision between an assembled
epic and staging. On approval the Release Manager merges the integration
branch into the epic branch (re-verifying if they diverged), then opens and
merges **one integration PR per repo** — head the epic branch, base the
integration branch, a merge commit so task history and a single-revert
demotion path survive. That merge is the release train assembling; from there
§6a applies unchanged: staging verification, then the human-merged promotion
PR at gate G3. If staging goes red and the diagnosis lands on this epic, its
integration merge commit is reverted and the epic returns to
`factory:on-epic` — one epic demoted, not the estate — and re-arms GS when it
is repaired and assembled again.

**Lifecycle end.** The epic branch is deleted by the Ops Monitor at archive
time — after the promotion PR carrying the epic has merged (or the epic issue
closes unshipped) — never earlier.

**Adoption and the flip.** An epic is on epic-branch routing when
`epics: true` **and** it has not been dispatched yet — that is, until gate G2
releases its tasks. Flipping the key is therefore safe at any moment: any
epic still short of G2 is adopted at its next gate approval, which creates
`factory/epic-<n>` (cut from the default branch, so it carries whatever the
epic has already merged there) and retargets any open document PR onto it —
a retarget keeps the PR, its reviews and its head branch.

Adoption does **not** depend on a document PR still being open. Either gate
can be reached by a human merging the document themselves, which is a route
this factory offers in as many words (§4); hanging adoption off an open PR
meant that route left the epic on default-branch routing for the rest of its
life, and its task PRs then based on the integration branch. The branch is
ensured at the gate whether or not there is anything left to retarget.

An epic **past G2** finishes on the routing it started with: its tasks are
already dispatched and some may have merged onto the integration branch, so a
fresh epic branch cut from the default branch would not carry them. The same
rule runs in reverse on a flip back to `false`.

**Writability.** Epic branches, like the integration branch, are
agent-writable (§8a); only the default branch is human-only. The fast lane is
unaffected: `factory:fast-track` changes have no epic and keep basing on the
integration branch.

## 7. Cross-repo epics

- The epic issue lives in the **coordination repo**, with sub-issues in each
  affected repo and an OpenSpec change folder in each affected repo.
- Dependency links are machine-readable body markers, one per line: `Blocked
  by #N` inside a repo, `Blocked by <owner>/<repo>#N` across repos; a
  sub-issue in a sibling repo names its epic with `Part of
  <owner>/<repo>#<epic>`. The Dispatcher and the Console both parse exactly
  these forms, so prose mentions of an issue never create an edge.
- The Architect keeps one shared API contract snippet **identical** across the
  repos' `design.md` files.
- A sub-issue closing re-dispatches its epic **in the epic's own repo**, read
  from that `Part of <owner>/<repo>#<epic>` marker — the task's title
  (`task(<epic>)`) gives the number, the marker gives the repo, and the title
  wins when the two disagree. The Actions engine needs
  `FACTORY_CROSS_REPO_TOKEN` to reach out of its own repository; without it
  the closing task gets a comment naming the epic and the dispatch to run
  over there, rather than a silent stop. The orchestrator engine acts for
  every repo it is installed on and needs nothing extra.
- Merge order is enforced by sub-issue dependencies and derived from the
  profiles' `estate_role`: **schema/data-model change → the repo that owns the
  contract → the repos that consume it**. Every intermediate merge must be
  releasable.
- The Release Manager treats the epic's PR set as one release train: with
  `epics: true`, every repo's `factory/epic-<n>` branch (same name in each
  affected repo, §6b) is complete and green before any repo's integration PR
  merges, and integration merges follow the contract-first order above; then
  every repo's piece is green on its integration branch (§6a) before any
  promotion PR is opened, and nothing is promoted to production until the
  whole train is. One repo red on staging holds the others on staging with it
  — that is cheap; a half-promoted estate is not.

## 8a. Protected-branch enforcement (no GitHub branch protection required)

Because branch protection needs a paid GitHub plan for private repos, the
factory enforces gate G3 itself, in three layers:

1. **PreToolUse hook** — `hooks/protect-branches.py`, shipped and wired by the
   plugin, blocks any agent `git push` whose destination is `main`/`master`
   (all refspec forms, force pushes, deletes, and bare `git push` while checked
   out on a protected branch), and any GitHub MCP write tool targeting those
   branches.
2. **Permission deny list** — `.claude/settings.json` **in the consuming repo**
   (a plugin cannot ship a permissions block) denies
   `mcp__github__merge_pull_request` and `mcp__github__enable_pr_auto_merge`,
   so agent sessions cannot merge PRs at all. **Humans merge via the GitHub
   UI**; that click is gate G3.
3. **Detection workflow** — `.github/workflows/factory-branch-guard.yml`
   fails and opens a `factory:incident` issue if a commit lands on `main`
   without an associated pull request.

The integration branch (§6a) and the epic branches (§6b) deliberately remain
agent-pushable so the Release Manager can assemble epics and release trains
autonomously; production (`main`) is human-only. That split is what makes the staging step work: the factory has a
branch it may write to and prove things on, and exactly one way — a human
merging a promotion PR — for anything to leave it.

Layer 3 also checks *where* a commit on `main` came from: a merge whose PR head
was not the integration branch (and whose diff is not documents-only, §6) is
reported on the incident issue as a change that skipped staging — an epic
branch merged straight to `main` is exactly that case: epic branches reach
`main` only through the integration branch (§6b). It is a
detection, not a block — a human may always merge whatever they judge necessary
— but it is never silent.

If the repos later move to a plan with branch protection/rulesets, turn them
on and this section becomes defence-in-depth rather than the primary control.

## 8. Guardrails

- Max **2 automatic rework rounds** per stage; then `factory:blocked` and a
  human is pinged.
- Agents re-read GitHub state and the change folder at the start of every run;
  sessions are disposable, artifacts are authoritative.
- Every agent-posted issue/PR comment ends with the literal marker line
  `<!-- factory-agent -->` (invisible when rendered) so comment-triggered
  automation can tell agent comments from human replies.
- No secrets in issues, OpenSpec artifacts or PRs.
- Reviewer security checklist: authz on new endpoints, parameterised SQL,
  input validation (Pydantic / class-validator), dependency diff, duplication
  check (extend existing code rather than duplicating it).

## 9. One-time setup (per repo)

1. **Issue template** — copy `templates/ISSUE_TEMPLATE/factory-requirement.yml`
   to `.github/ISSUE_TEMPLATE/factory-requirement.yml`, editing the "Affected
   repositories" checkboxes to match your estate. This is the intake entry
   point (§10); the `factory:intake` label it applies only starts the pipeline
   once the labels step below has run.
2. **Labels** — `GITHUB_TOKEN=... bash scripts/setup-labels.sh <owner> <repo...>`
   creates the 25 `factory:*` labels (§3). Run it once per repo, and again
   after a factory upgrade that adds labels — `factory:expedite` and
   `factory:epic-ready` are the newest (§4a).
3. **Secrets** — add `ANTHROPIC_API_KEY` *or* `CLAUDE_CODE_OAUTH_TOKEN` as a
   **repository** secret (Settings → Secrets and variables → Actions).
   Environment secrets do *not* reach jobs that don't declare `environment:`,
   which is a common first-run failure. Add `FACTORY_CROSS_REPO_TOKEN` too if
   the estate has more than one repo (§2a).
4. **OpenSpec** — `npx -y @fission-ai/openspec@latest init --tools claude`
   (needs Node 20.19+). This installs the `/opsx:*` commands and their skills;
   the factory depends on them but does not vendor them.
5. **Profile** — `.factory/profile.json` (§2c). Easiest path: file an issue
   labelled `factory:profile` (the Factory Console does this for you) and the
   **Profiler** drafts it from the code in your own runner, then opens a PR for
   you to check and merge. To write it by hand instead, start from
   `templates/profile.example.json` and validate against
   `templates/profile.schema.json`. Either way the contents are yours: the
   Profiler proposes, a human merges.
6. **Releases (optional)** — copy `templates/factory-release.json` to
   `.github/factory-release.json` to gate intake behind milestones (§2d), and
   add a `release_scope` list to `.github/factory-approvers.json`. Leave the
   file out to keep the original behaviour.
6a. **Integration branch and epic branches** — copy
   `templates/factory-branches.json` to `.github/factory-branches.json` and
   set `staging` to whatever your org calls its integration/test branch. Copy
   the *same* file into every repo in the estate: this is one org decision.
   Omitting the file is not opting out — the defaults (`staging`, required,
   auto-created, no epic branches) apply either way; to opt out of staging,
   ship the file with `"required": false`. The template ships with
   `"epics": true`, giving every epic its own `factory/epic-<n>` branch
   (§6b); drop the key (or set `false`) for the pre-epic behaviour. Flipping
   `epics` later is safe at any moment: an epic only follows the new value
   while none of its gate documents has merged (§6b). Neither branch needs
   manual setup while `auto_create` is on (§6a).
7. **Install the factory** — §10.
8. Protected-branch enforcement is factory-side (§8a) — nothing to configure on
   GitHub. If you later move to a plan with branch protection or rulesets, turn
   them on as well: require 1 approval and green CI on `main`, and green CI on
   the integration branch. Do **not** protect the integration branch against
   the factory itself — the Release Manager has to be able to merge onto it,
   and that is the whole staging step (§6a).

## 10. How the factory is distributed

The factory is one repository consumed two ways, because GitHub only runs
workflow files that physically exist in the repo being built — a Claude Code
plugin cannot deliver them.

| Channel | Delivers | Mechanism |
|---|---|---|
| Claude Code plugin `factory` | the 12 role prompts, this handbook, the protected-branch hook | marketplace install, or `--plugin-dir` for local development |
| Reusable GitHub Actions workflows | the pipeline, the test harness, the branch guard | `uses: <owner>/claude-software-factory/.github/workflows/<file>@v1` |

Both channels serve the same files from the same tagged commit. In CI the
runner clones this repo at `factory_ref` into `RUNNER_TEMP` (deliberately
outside the workspace, so an agent's `git add` cannot sweep it into a PR) and
injects the handbook plus the role prompt into the agent's prompt directly.

### The consuming repo's whole footprint

| File | Why it can't live in the plugin |
|---|---|
| `.factory/profile.json` | It *is* the per-repo part (§2c) |
| `.github/workflows/factory-pipeline.yml` | ~15-line caller stub — GitHub only fires workflows present in the repo |
| `.github/workflows/factory-branch-guard.yml` | same |
| `.github/factory-models.json` | per-repo model tuning; read from the caller's checkout |
| `.github/factory-approvers.json` | per-repo gate approvers |
| `.github/factory-release.json` | per-repo release gating (§2d); optional — omit it and intake runs on every filed issue |
| `.github/factory-branches.json` | the org's integration-branch policy (§6a); optional — omit it and the defaults (`staging`, required, auto-created) apply |
| `.github/factory-orchestrator.json` | per-repo engine choice (§2e); optional — omit it and GitHub Actions drives the repo |
| `.github/ISSUE_TEMPLATE/factory-requirement.yml` | the intake entry point — GitHub only renders issue forms present in the repo being filed against |
| `.claude/settings.json` | plugin `settings.json` supports only `agent` and `subagentStatusLine` — a **permissions** block cannot ship in a plugin, and the merge deny list is half of §8a |

Templates for all of these are in `templates/`. Nothing else is copied: the
pipeline body, the role prompts and the hook all stay here.

**The stubs must declare `permissions:` themselves.** A called workflow's token
is capped by the caller's, so a stub that omits the block inherits the repo
default and the run dies at startup — `startup_failure`, before any job, with
the reference itself resolving fine. The templates carry the right blocks; keep
them if you edit a stub.

### Installing the plugin

```bash
claude plugin marketplace add <owner>/claude-software-factory
claude plugin install factory@<owner>
```

Once per machine. The `extraKnownMarketplaces` / `enabledPlugins` keys in
`.claude/settings.json` declare the marketplace and record the intent, but do
**not** install on their own — verified: with only those keys and no prior
install, `/factory:*` does not load. CI needs no install at all; the reusable
workflows clone this repo directly.

### Versioning

`v1` is a **branch** that tracks the current stable major version. Consuming
repos pin it in both the `uses:` ref and the `factory_ref` input — keep the two
in sync, they sit next to each other in the stub for exactly that reason.
Releasing means fast-forwarding `v1` to a reviewed commit on `main`.

Because every repo resolves the same ref, a bad release breaks the whole estate
at once. Two mitigations, both cheap:

- Advance `v1` only after a canary repo has run the new code.
- Keep one repo pinned to `@main` as that canary.

For a stricter supply-chain posture, pin the `uses:` ref to a commit SHA. An
annotated tag works identically to the `v1` branch if you prefer immutable
release markers — `git tag v1.2.0 && git push origin v1.2.0`, then point stubs
at it.

### Local development

```bash
claude --plugin-dir /path/to/claude-software-factory   # load without installing
claude plugin validate /path/to/claude-software-factory
```

`--plugin-dir` overrides an installed copy for that session, so a change to a
role prompt can be exercised against a real repo before it is tagged.
