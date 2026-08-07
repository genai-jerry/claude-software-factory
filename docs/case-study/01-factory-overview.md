# The Lighthouse Software Factory — How It Works

Version 1.0 · Status: piloted end-to-end, pending merge to `main`

## 1. What it is

The Lighthouse Software Factory turns a plain GitHub issue into reviewed,
tested, production-bound code across four repositories, driven by a chain of
specialised AI agents. A person writes what they need; agents handle analysis,
planning, technical design, implementation, review and testing; a person
approves at three gates and presses the merge button.

Repositories under factory management:

| Repository | Stack | Role |
|---|---|---|
| `lighthouse-backend` | Python 3.12, FastAPI, MySQL, Alembic | Coordination repo — epics filed here |
| `lighthouse-ui` | React 19, Vite, TypeScript, MUI | Frontend implementer |
| `lighthouse-sales` | FastAPI, Postgres/pgvector, Celery | Sales automation implementer |
| `lighthouse-whatsapp-server` | NestJS, Prisma, BullMQ | Messaging implementer |

## 2. Two foundations, one rule

The design separates **where work is** from **what is being built**:

- **GitHub is the state machine.** Issues, sub-issues, labels and milestones
  encode pipeline position. Label transitions trigger agents. The issue list
  filtered by `factory:*` is the live dashboard.
- **OpenSpec is the artifact layer.** The proposal, WHEN/THEN requirement
  scenarios, technical design and task checklist live as plain Markdown in
  `openspec/changes/<epic>-<slug>/`, versioned in the repo.

**The rule: issues carry state plus a link — never spec content.** Agents read
requirements from the change folder, never from an issue body. This prevents
the two-sources-of-truth drift that kills spec-driven workflows, and it makes
every stage resumable: agent sessions run in ephemeral containers, so anything
not committed is lost. Committed artifacts mean a crashed run costs nothing.

## 3. Architecture

Four layers, communicating only through GitHub — agents never talk to each
other directly, which keeps every hand-off inspectable.

```
SOURCE OF TRUTH   Issues & labels │ openspec/ folders │ Pull requests │ Actions CI
                                  ▲
ORCHESTRATION     factory-pipeline.yml — event-driven, stateless routing
                                  ▲
AGENT LAYER       9 role prompts × Claude Code sessions (per-stage models)
                                  ▲
HUMANS / RUNTIME  Gate approvals G1–G3        AWS Lightsail staging & production
```

The orchestrator is deliberately **not** an AI agent: it is a routing job in a
GitHub Actions workflow that reads labels and launches the right role. It holds
no state, so any human can drive or override the pipeline by editing labels.

## 4. The pipeline

| # | Stage | Agent | Produces |
|---|---|---|---|
| 1 | Intake | Intake Analyst | `proposal.md` + `specs/` (WHEN/THEN scenarios), as a PR |
| 2 | Plan | Planner | `tasks.md` (≤10 tasks) mirrored into sub-issues; opens the design PR |
| 3 | Design | Architect | `design.md` per affected repo; shared API contract snippet |
| 4 | Dispatch | Dispatcher | Marks dependency-clear tasks `factory:ready` |
| 5 | Implement | Implementer (per repo) | Branch + tests + draft PR, one per task |
| 6 | Review | Reviewer | Independent line-level review; approve or bounce back |
| 7 | Test | QA Engineer | Scenario→test mapping, suites green, test report |
| 8 | Deploy | Release Manager | Dependency-ordered merges, staging watch, promotion list |
| 9 | Verify | Ops Monitor | Smoke checks, soak, `/opsx:archive`, issue closure |

**Human gates.** G1: approve the spec PR. G2: approve the plan+design PR.
G3: merge to production. Everything else runs unattended. Gates are async —
each presents a short Markdown document to review, not a transcript.

**Triggers** (`factory-pipeline.yml`):

| Event | Runs |
|---|---|
| Any issue opened | Auto-applies `factory:intake`, runs Intake Analyst |
| `factory:spec-approved` applied (G1) | Planner, then Architect chained in-run |
| `factory:design-approved` applied (G2) | Dispatcher |
| Comment `Approved` on a gate issue | Merges the gate PR, flips the label, continues |
| Comment on a `factory:blocked` issue | Clears the block, re-runs the stalled stage |
| Actions → Run workflow | Any role, any issue (manual/retry path) |

Bot-authored issues, `task(...)` sub-issues and issues already in the pipeline
are skipped, so the factory cannot recursively trigger itself. Agent comments
carry an invisible `<!-- factory-agent -->` marker for the same reason.

## 5. Configuration

Everything is file-based and version-controlled — no console, no database.

| File | Purpose |
|---|---|
| `FACTORY.md` | Canonical conventions: stages, labels, gates, branching, guardrails |
| `.github/factory-models.json` | Model preference chain per role |
| `.github/factory-approvers.json` | Gate → responsible GitHub usernames |
| `.github/workflows/factory-pipeline.yml` | Event routing and agent launch |
| `.github/workflows/factory-branch-guard.yml` | Detects direct pushes to `main` |
| `.claude/commands/factory/*.md` | The 9 role prompts |
| `.claude/settings.json` | Denies PR-merge tools; wires the branch-guard hook |
| `.claude/hooks/protect-branches.py` | Blocks agent pushes to `main`/`master` |
| `openspec/config.yaml` | Per-repo stack context and artifact rules |

**Model routing.** Each role names a preference chain; the workflow probes each
model with a one-token ping and uses the first the credential can reach, so a
plan/tier gap degrades gracefully instead of failing:

- Intake, Planner, Architect, Reviewer → Fable 5 → Opus 5 → Sonnet 5
- Implementer, QA, Release → Opus 5 → Sonnet 5
- Dispatch, Ops → Haiku 4.5 → Sonnet 5

The principle: spend model quality where errors compound (a wrong contract or a
missed review defect multiplies downstream), economise where volume lives.

**Approvers.** Each gate maps to usernames. On hand-off the pipeline assigns
the issue and posts an @-mention, so GitHub's own notification machinery does
the work. Approvals from anyone not on the gate's list are ignored or reverted.

**Secrets** (per repo): `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`, and
`FACTORY_CROSS_REPO_TOKEN` — a fine-grained PAT spanning the four repos, which
lets the Planner create sub-issues and the Architect push designs across repos.

## 6. Guardrails

GitHub branch protection needs a paid plan, so gate G3 is enforced
factory-side in three layers: a **PreToolUse hook** blocks every form of agent
push to `main`/`master` (refspecs, force, delete, bare push while checked out);
a **permission deny list** removes PR-merge tools from agent sessions entirely;
and a **detection workflow** opens a `factory:incident` issue if a commit ever
lands on `main` without a PR. `staging` stays agent-pushable so release trains
assemble autonomously; production is human-only.

Additional limits: max 2 automatic rework rounds per stage before
`factory:blocked`; one task per implementer session; deploy workflows
`paths-ignore` the document paths so merging specs to `main` never deploys.

## 7. Pilot evidence

Issue #162 ("show appointments booked as a percentage of leads") ran the full
pipeline:

- **Intake** read the codebase and stopped with four scope-changing questions —
  including that the repo has *two* divergent monthly-target concepts. It did
  not guess. After answers, it produced PR #163 (proposal + 5 scenarios) and
  correctly scoped the epic as **UI-only**, since existing endpoints already
  served the data.
- **Planner** cut 2 tasks, created sub-issues in `lighthouse-ui` (#145, #146)
  with a dependency link and a milestone — the first live cross-repo write.
- **Architect** wrote `design.md` in both repos with a byte-identical contract
  snippet, grounded in the real components (`SummaryCards.tsx`,
  `getGradeColorClass`), and merged as PR #164 / ui #147 at G2.
- **Implementer** produced ui PR #148: a small pure module with colocated
  Vitest tests covering the spec scenarios, and — notably — left the
  colour-coding to task #146 with a comment, respecting the task boundary.

Two behavioural gaps surfaced and were fixed in the prompts: the Dispatcher
only labelled tasks in its own repo, and OpenSpec CLI/action integration
details differed from assumptions. That is exactly what a pilot is for.

## 8. Status and next steps

Complete: all four repos scaffolded; labels, prompts, workflows, guardrails,
model routing and approver notifications in place; the pipeline exercised
through implementation via a branch-scoped test harness.

Remaining: finish the pilot (review → QA → merge → second task), then **merge
the factory to `main` in all four repos** — issue-event triggers only fire from
the default branch, so the automation arms at that moment. After that, Phase 6:
metrics (cycle time, rework rate per stage), a stuck-work sweeper, and
evaluation of OpenSpec Stores for centralised cross-repo planning.
