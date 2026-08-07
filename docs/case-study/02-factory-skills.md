# The Factory Skills and Role Prompts

Version 1.0 · What each agent capability is, when it fires, and what it produces

## 1. Two families

The factory runs on two families of Markdown-defined capabilities, both living
in `.claude/` and both version-controlled alongside the code they act on:

- **OpenSpec skills** (6) — installed by the OpenSpec CLI. They know how to
  create and maintain the *artifacts*: proposals, specs, designs, task lists.
  They are generic: they know nothing about Lighthouse.
- **Factory role prompts** (9) — written for this estate. They know the
  *pipeline*: which label to read, which artifact to produce, which label to
  set next, what to refuse. They call OpenSpec skills to do artifact work.

The division matters: OpenSpec supplies the document machinery, the role
prompts supply the process and the judgement.

## 2. OpenSpec skills

Installed per repo by `openspec init --tools claude`, surfaced both as skills
(`.claude/skills/<name>/SKILL.md`) and as slash commands
(`.claude/commands/opsx/*.md`). Configured by `openspec/config.yaml`, which
carries each repo's stack context and per-artifact rules.

| Skill / command | What it does | Used by |
|---|---|---|
| `openspec-explore` `/opsx:explore` | Thinking mode: reads code, weighs options, clarifies requirements before committing to a plan | Intake |
| `openspec-propose` `/opsx:propose` | Creates the change folder and generates all artifacts in one step — `proposal.md`, `specs/<capability>/spec.md`, `design.md`, `tasks.md` | Intake |
| `openspec-apply-change` `/opsx:apply` | Implements tasks from `tasks.md`, one unchecked item at a time | Implementer |
| `openspec-update-change` `/opsx:update` | Revises a change's planning artifacts and keeps them coherent with each other. Never edits code | Architect, rework rounds |
| `openspec-sync-specs` `/opsx:sync` | Folds a change's delta specs into the repo's main `openspec/specs/` without archiving | Ops (optional) |
| `openspec-archive-change` `/opsx:archive` | Moves a completed change to `openspec/changes/archive/` and merges durable requirements into main specs | Ops Monitor |

**Artifact anatomy.** A change folder is four files that map one-to-one onto
pipeline stages — which is precisely why OpenSpec was adopted as the artifact
layer:

```
openspec/changes/162-appointments-booked-percentage/
├── proposal.md    problem, scope, non-goals, affected repos   (Intake, gate G1)
├── specs/…/spec.md  WHEN/THEN scenarios = acceptance criteria (Intake, gate G1)
├── tasks.md       ordered checklist, one PR each              (Planner, gate G2)
└── design.md      contracts, migrations, failure modes        (Architect, gate G2)
```

**Repo rules** in `openspec/config.yaml` constrain generation — for example the
backend requires a Non-goals section, individually testable scenarios, tasks of
at most half a day, and designs that name the existing modules to extend rather
than duplicate.

## 3. Factory role prompts

Each is a Markdown file with frontmatter (`description`) and a body specifying
**trigger, mission, numbered steps, and guardrails**. `$ARGUMENTS` receives the
issue or PR number. Invoked as `/factory:<role>` in a session, or launched by
the pipeline workflow in Actions.

Epic-level roles are identical in every repo so a requirement can be filed
anywhere; `implementer`, `reviewer` and `qa` are flavoured per stack.

### 3.1 Intake Analyst — `factory:intake`

Turns a raw request into a testable specification. Explores the codebase and
existing `openspec/specs/`, detects duplicates, and — critically — **stops and
asks** rather than inventing requirements: ambiguity produces one comment of
numbered questions and `factory:blocked`. Otherwise it runs explore + propose,
opens the spec PR, and cc's the G1 approvers.
*Guardrail: never plan tasks or design solutions; spec content lives only in
the change folder.*

### 3.2 Planner — `factory:spec-approved`

Decomposes the approved spec into `tasks.md`: each task one PR of ≤ half a day,
at most ~10 per change (OpenSpec degrades beyond that envelope), ordered so
every intermediate merge is releasable — migration → backend → consumers. It
mirrors the checklist into GitHub sub-issues in each task's target repo with
"Blocked by #N" links, creates the milestone, and opens the shared design PR.
*Guardrail: tasks say WHAT, not HOW; every spec scenario must map to a task.*

### 3.3 Architect — `factory:planned`

Reads the **actual code** of every affected repo before deciding anything, and
searches for existing modules to extend — duplication is treated as a design
failure, since that is OpenSpec's known blind spot. Produces `design.md` per
repo: API contracts, migration plans, component changes, failure modes per
scenario, rollout and rollback. The shared contract snippet must be
byte-identical across repos. Adds to the Planner's branch so plan and design
are one G2 approval.
*Guardrail: no code beyond illustrative snippets; every task must be
implementable from the design alone.*

### 3.4 Dispatcher — `factory:design-approved`

Mechanical coordination, no judgement: reads `tasks.md`, lists sub-issues
across **every** affected repo, and applies `factory:ready` to those whose
dependencies are all merged. Summarises what is ready and what remains blocked,
cc'ing the implementation approvers.
*Guardrail: never mark a task ready while a dependency is open — releasability
depends on merge order.*

### 3.5 Implementer (per repo) — `factory:ready`

Takes exactly one task. Branches `factory/<task>-<slug>`, follows `design.md`
and the repo's own conventions, writes the required tests, runs that repo's
suite (`pytest` / `vitest` + build / `jest`), opens a **draft** PR linking the
task and change folder, and checks the item off in `tasks.md`.
*Guardrails: one task per session — never start the next; if the design is
wrong, stop and `factory:blocked` rather than silently redesigning.*

Stack flavouring: the backend variant enforces raw-SQL stores with `run_db` and
the `APIResponse` envelope; the UI variant centralises calls in
`services/api.ts` and requires loading/empty/error states; sales knows Alembic
runs on startup and Celery is opt-in; whatsapp knows Prisma migrations and the
mock provider's deliberate 10% failure rate.

### 3.6 Reviewer — draft PR opened

An **independent** session that never shares the implementer's context. Checks
conformance to `design.md` and the spec scenarios, correctness and edge cases,
security (authz on new endpoints, parameterised SQL, input validation, secret
hygiene), repo conventions, and duplication of existing code. Approves to
`factory:in-test`, or requests changes back to `factory:ready` — maximum two
automatic rounds, then a human is pinged.
*Guardrail: review the fetched diff, not the PR description's claims; never
merge.*

### 3.7 QA Engineer — `factory:in-test`

Maps every WHEN/THEN scenario to a concrete test and writes the missing ones,
then runs the full suite and watches CI, posting a scenario → test → status
table on the PR.
*Guardrail: a scenario "covered" by code inspection is not covered — only
executing tests count as evidence; never weaken a test to make it pass.*

### 3.8 Release Manager — all task PRs green

Computes merge order from dependency links, merges to `staging`, watches the
deploy and health endpoints, then posts a **numbered merge list** for the human
to execute (gate G3). It cannot merge to production — the tooling forbids it.
*Failure handling: a red staging deploy halts the train; a failed production
deploy triggers rollback and `factory:incident`.*

### 3.9 Ops Monitor — `factory:deployed`

Runs smoke checks (`/api/health`, `/api/health/pool`, key flows), scans logs
for new error signatures across a soak window, then archives the change and
closes the epic with a scenario → evidence summary. On regression it files a
`factory:incident` and withholds the archive.

## 4. How they compose

```
issue → intake ─G1→ planner → architect ─G2→ dispatch → implementer
                                                            ↓
                        ops ←─G3─ release ← qa ← reviewer ──┘
```

Each role reads GitHub state plus the change folder at start, does one job,
writes results back, and exits. No role trusts another's summary — the Reviewer
re-reads the diff, QA re-runs the tests, Ops re-checks production. That
redundancy is deliberate: it is what makes an unattended chain safe.

## 5. Extending or modifying a role

1. Edit `.claude/commands/factory/<role>.md` — trigger, steps, guardrails.
2. Replicate to the other repos if it is an epic-level role (they are identical
   by design); keep stack-specific detail only in implementer/reviewer/qa.
3. Adjust `.github/factory-models.json` if the role's reasoning demands change.
4. Merge to `main` — Actions reads prompts from the default branch.

Prompts are the highest-leverage thing to tune: both pilot defects were fixed
by editing a prompt, not code. Behaviour lives in Markdown, under review, in
git history.
