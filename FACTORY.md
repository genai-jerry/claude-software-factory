# The Software Factory

This is the **canonical conventions document** for an agent-driven delivery
pipeline: requirement issue → spec → tasks → design → code → review → test →
release → verification, with agents doing the work and humans holding three
gates.

It is repo-agnostic. Everything a role needs to know about a *particular*
codebase lives in that repo's `.factory/profile.json` (§2c) — never in these
prompts. An estate of N repositories runs N profiles and one copy of this
document.

**How it reaches your repos:** this file, the nine role prompts, and the
protected-branch hook ship as the `factory` Claude Code plugin; the pipeline
ships as reusable GitHub Actions workflows. A consuming repo holds five files,
none of them logic. See §10.

---

## 1. Two foundations, one rule

- **GitHub is the state machine.** Issues, sub-issues, labels and milestones
  encode *where* every piece of work is. Labels trigger agents.
- **OpenSpec is the content.** *What* is being built — proposal, WHEN/THEN
  requirement scenarios, technical design, task checklist — lives in
  `openspec/changes/<epic-issue-number>-<slug>/` in each affected repo.

**The rule: issues carry state plus a link to the change folder — never spec
content. Agents read requirements from the change folder, never from the issue
body.** This prevents the two-sources-of-truth drift.

## 2. Pipeline stages and agents

| # | Stage | Agent (role prompt) | Produces |
|---|---|---|---|
| 1 | Intake | `/factory:intake` | `proposal.md` + `specs/` via `/opsx:explore` + `/opsx:propose`, opened as a PR |
| 2 | Plan | `/factory:planner` | `tasks.md` (≤ ~10 tasks, one PR each) mirrored into GitHub sub-issues; opens the shared design PR |
| 3 | Design | `/factory:architect` | `design.md` per affected repo (same branch/PR as `tasks.md` in the epic's repo); shared contract snippet identical across repos |
| 4 | Implement | `/factory:implementer` | Branch + commits + draft PR per task via `/opsx:apply` |
| 5 | Review | `/factory:reviewer` | Line-level review; approve or request changes |
| 6 | Test | `/factory:qa` | Scenario→test mapping, full suites green, test report on PR |
| 7 | Deploy | `/factory:release` | Dependency-ordered merges, staging watch, production promotion |
| 8 | Verify | `/factory:ops` | Health/smoke checks, soak, `/opsx:archive`, issue closure |

Role prompts are supplied by the `factory` plugin, so every repo runs the
**same nine prompts** — there is no per-repo copy to drift. Stack-specific
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
| Any issue opened (human-authored, not `task(...)`, no factory state yet) | Auto-applies `factory:intake`, then runs the **Intake Analyst** |
| Human applies `factory:spec-approved` (gate G1) | **Planner**, then **Architect** chained in the same run |
| Human applies `factory:design-approved` (gate G2) | **Dispatcher** — marks unblocked tasks `factory:ready` |
| Owner/collaborator comments exactly `Approved` on an issue in `factory:spec-ready` or `factory:design-ready` | The gate's document PR(s) in this repo are squash-merged, the label flips to the approved state, and the next stage (Planner→Architect, or Dispatcher) runs in the same workflow run. Strict match — "Approved, but..." is just a comment. G3 is deliberately not comment-approvable |
| Human replies on a `factory:blocked` issue | `factory:blocked` is cleared and the blocked stage re-runs, re-reading the whole thread (agent comments carry an `<!-- factory-agent -->` marker so they never self-trigger) |
| Actions → "Factory pipeline" → *Run workflow* | Any role on any issue/PR number (the manual/retry path; used for implementer/reviewer/qa/release/ops until those are event-wired) |

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
| intake, planner, architect, reviewer | `claude-fable-5` → `claude-opus-5` → `claude-sonnet-5` | Errors here compound downstream: a wrong spec/plan/design or a missed review defect costs far more than the model delta |
| implementer, qa, release | `claude-opus-5` → `claude-sonnet-5` | Strong coding/testing quality on the volume stages, guardrailed by the merged design.md and spec scenarios |
| dispatch, ops | `claude-haiku-4-5-20251001` → `claude-sonnet-5` | Mechanical label routing and health-check verification |

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
| `branches` | implementer, release | `default` + `staging` (null when the repo has no staging train) |
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
writing one profile, not rewriting nine prompts.

## 2b. Approvers and notifications

`.github/factory-approvers.json` in the consuming repo maps each gate to
the GitHub usernames responsible for it:

| Key | Responsibility | Notified when | How they act |
|---|---|---|---|
| `spec` | Gate G1 — approve the spec PR | Issue reaches `factory:spec-ready` | Merge the PR + apply the label, or comment `Approved` |
| `design` | Gate G2 — approve the plan+design PR | Issue reaches `factory:design-ready` | Same |
| `implementation` | Start implementers on ready tasks | A task reaches `factory:ready` | Run workflow (role: implementer) |
| `release` | Gate G3 — production go | Release Manager posts the merge list | Merge the staging→main PRs in order |

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

## 3. Label state machine

State labels are mutually exclusive; exactly one `factory:*` state label per
issue at a time. Create them with `scripts/factory/setup-labels.sh`.

| Label | Meaning | Set by | Advanced by |
|---|---|---|---|
| `factory:intake` | New requirement awaiting analysis | Issue template | Intake → `factory:spec-ready` |
| `factory:spec-ready` | Spec PR open, awaiting **gate G1** | Intake | Human merges spec PR → `factory:spec-approved` |
| `factory:spec-approved` | Released for planning | Human (G1) | Planner → `factory:planned` |
| `factory:planned` | tasks.md + sub-issues created | Planner | Architect → `factory:design-ready` |
| `factory:design-ready` | design.md PR(s) open, awaiting **gate G2** | Architect | Human merges design PR → `factory:design-approved` |
| `factory:design-approved` | Released for implementation | Human (G2) | Orchestrator → `factory:ready` on unblocked tasks |
| `factory:ready` | Task unblocked; implementer may start | Orchestrator | Implementer → `factory:in-review` |
| `factory:in-review` | Draft PR under agent review | Implementer | Reviewer → `factory:in-test` (or back to `factory:ready`) |
| `factory:in-test` | QA verifying scenarios | Reviewer | QA → `factory:ready-to-ship` |
| `factory:ready-to-ship` | Awaiting merge order & **gate G3** | QA | Release → `factory:deployed` |
| `factory:deployed` | In production, soak in progress | Release | Ops archives + closes, or files `factory:incident` |
| `factory:fast-track` | Small fix bypassing OpenSpec ceremony | Human triage | Normal PR flow (review + CI only) |
| `factory:blocked` | Needs human attention | Any agent | Human |
| `factory:incident` | Post-deploy regression | Ops Monitor | Human + Release (rollback) |

## 4. Human gates

- **G1 — Spec approval:** review the `proposal.md` + `specs/` PR, then either
  merge it and apply `factory:spec-approved`, or simply comment `Approved` on
  the epic (the pipeline merges the PR and flips the label for you).
- **G2 — Design approval:** review the design PR(s) — one per affected repo;
  in the epic's repo it carries both `tasks.md` and `design.md` — then either
  merge and apply `factory:design-approved`, or comment `Approved` on the epic.
  Note: comment approval merges the design PR in the epic's repo; sibling-repo
  design PRs still need their own merge.
- **G3 — Merge & release:** every PR into `main` is merged **by a human via
  the GitHub UI** — never by an agent. Promotion from `staging` to `main`
  (production) likewise requires an explicit human go. GitHub branch
  protection is not available on the current plan, so this is enforced
  factory-side (see §8a): agents are hard-blocked from pushing to `main` and
  from using PR-merge tools. The merge button *is* the gate.

Everything else runs unattended. Any human may take over any stage at any time
by doing the work manually and setting the next label.

## 5. OpenSpec conventions

- **Change naming:** `openspec/changes/<epic-issue-number>-<slug>/`
  (e.g. `openspec/changes/123-payment-reminders/`).
- **Scope:** one change per epic, **max ~10 tasks**. The Planner splits larger
  epics into sequential changes.
- **Fast-track bypass:** bug fixes and trivial tweaks skip OpenSpec entirely —
  label `factory:fast-track`, normal PR flow.
- **Commands (OpenSpec v1.7 core profile):** `/opsx:explore`, `/opsx:propose`,
  `/opsx:apply`, `/opsx:update`, `/opsx:sync`, `/opsx:archive`.
- **Archive:** only the Ops Monitor archives, and only after production soak
  passes. Durable requirements accumulate in `openspec/specs/`.
- **Telemetry:** disabled — set `OPENSPEC_TELEMETRY=0` in agent environments.

## 6. Branching and PRs

- Spec branch: `factory/<epic-issue>-spec`; shared plan+design branch:
  `factory/<epic-issue>-design` (carries `tasks.md` + `design.md` in the
  epic's repo; `design.md` only in sibling repos).
- Task branches: `factory/<task-issue-number>-<slug>` cut from the repo's
  default branch.
- One task = one PR. PR body links its task issue (`Closes #N`) and the change
  folder, and notes any deviation from `design.md`.
- Draft PR until the Reviewer marks it ready. CI must be green before
  `factory:ready-to-ship`.

### Where PRs merge (base branches)

- **Document PRs (spec, plan+design):** into the repo's **default branch**
  (`main`). Safe by construction: the deploy workflows now `paths-ignore` the
  factory/document paths (`openspec/**`, `docs/**`, `FACTORY.md`,
  `.claude/**`, factory workflow files), so a docs-only merge to main deploys
  nothing. Merging docs to main is required so every later stage — which
  clones the default branch — can see the approved artifacts.
- **Implementation (task) PRs:** into **`staging`** where the repo has one
  (backend, ui, sales), else the default branch. Merging to staging
  auto-deploys the staging environment — that's the release train assembling.
- **Production promotion (gate G3):** one `staging` → `main` PR per repo,
  merged by a human in the Release Manager's posted order. That merge is the
  production deploy.
- During the pre-merge pilot, all PRs base on the factory development branch
  instead.

## 7. Cross-repo epics

- The epic issue lives in the **coordination repo**, with sub-issues in each
  affected repo and an OpenSpec change folder in each affected repo.
- The Architect keeps one shared API contract snippet **identical** across the
  repos' `design.md` files.
- Merge order is enforced by sub-issue dependencies and derived from the
  profiles' `estate_role`: **schema/data-model change → the repo that owns the
  contract → the repos that consume it**. Every intermediate merge must be
  releasable.
- The Release Manager treats the epic's PR set as one release train: nothing is
  promoted to production until every repo's piece is green on staging.

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

`staging` deliberately remains agent-pushable so the Release Manager can
assemble release trains autonomously; production (`main`) is human-only.
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

1. **Labels** — `GITHUB_TOKEN=... bash scripts/setup-labels.sh <owner> <repo...>`
   creates the 14 `factory:*` labels (§3). Run it once per repo.
2. **Secrets** — add `ANTHROPIC_API_KEY` *or* `CLAUDE_CODE_OAUTH_TOKEN` as a
   **repository** secret (Settings → Secrets and variables → Actions).
   Environment secrets do *not* reach jobs that don't declare `environment:`,
   which is a common first-run failure. Add `FACTORY_CROSS_REPO_TOKEN` too if
   the estate has more than one repo (§2a).
3. **OpenSpec** — `npx -y @fission-ai/openspec@latest init --tools claude`
   (needs Node 20.19+). This installs the `/opsx:*` commands and their skills;
   the factory depends on them but does not vendor them.
4. **Profile** — write `.factory/profile.json` (§2c). Start from
   `templates/profile.example.json`; validate against
   `templates/profile.schema.json`. This is the only file whose contents are
   genuinely yours to author.
5. **Install the factory** — §10.
6. Protected-branch enforcement is factory-side (§8a) — nothing to configure on
   GitHub. If you later move to a plan with branch protection or rulesets, turn
   them on as well: require 1 approval and green CI on `main` (and `staging`).

## 10. How the factory is distributed

The factory is one repository consumed two ways, because GitHub only runs
workflow files that physically exist in the repo being built — a Claude Code
plugin cannot deliver them.

| Channel | Delivers | Mechanism |
|---|---|---|
| Claude Code plugin `factory` | the 9 role prompts, this handbook, the protected-branch hook | marketplace install, or `--plugin-dir` for local development |
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
