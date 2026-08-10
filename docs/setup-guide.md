# Setup guide: installing the factory in a repo

Step-by-step instructions for pointing the factory at one repository. For the
concepts behind each step, see [`FACTORY.md`](../FACTORY.md); this document
only covers *doing* the install. Where the two disagree, `FACTORY.md` wins.

## Before you start

- Node 20.19+ (needed for OpenSpec).
- A GitHub token with `repo` scope, to create labels.
- Push access to the repo, including its Settings → Secrets page.
- An Anthropic API key or a `claude setup-token` OAuth token.
- Decide, up front:
  - **Does this repo have a `staging` branch?** Task PRs merge to staging when
    one exists, otherwise to `default` (FACTORY.md §6).
  - **Is this repo part of a multi-repo estate?** If so, pick one repo as the
    **coordination repo** — the one that owns the shared contract — and plan
    to get `FACTORY_CROSS_REPO_TOKEN` (a fine-grained PAT with Issues +
    Contents + Pull requests on every repo in the estate).
  - **Should filing an issue start an agent immediately?** If work here is
    planned in releases, turn on release gating in step 4 — issues then wait in
    `factory:backlog` until their milestone is approved (FACTORY.md §2d).

Every step below runs from the consuming repo's root unless noted otherwise.

## 1. Create the `factory:*` labels

```bash
GITHUB_TOKEN=<token> bash scripts/setup-labels.sh <owner> <repo>
```

Run from a checkout of **this** repo (`claude-software-factory`), pointed at
the *consuming* repo via `<owner> <repo>`. It creates (or updates) the 19
labels listed in FACTORY.md §3 — the mutually-exclusive states plus
`factory:release`, the kind marker on release tracker issues. Safe to re-run —
existing labels are patched in place, not duplicated. Pass multiple `<repo>`
arguments to label several repos in one estate at once.

## 2. Install OpenSpec

```bash
cd /path/to/your/repo
npx -y @fission-ai/openspec@latest init --tools claude
```

This installs the `/opsx:*` commands and skills the factory's intake,
implementer and ops roles depend on. OpenSpec is not vendored in this repo —
it's a separate dependency, installed once per consuming repo.

## 3. Write the repo profile

```bash
mkdir -p .factory
curl -o .factory/profile.json \
  https://raw.githubusercontent.com/genai-jerry/claude-software-factory/v1/templates/profile.example.json
```

Open `.factory/profile.json` and replace **every** value — it's the one file
in this whole setup that's genuinely yours. It's data, not prose: only facts
a role can act on (runnable test/build/lint commands, real conventions, known
failing tests, runnable health-check commands), never aspirations. See
FACTORY.md §2c for what each field feeds and `templates/profile.schema.json`
for the schema to validate against. A missing or unparseable profile
hard-blocks the per-repo roles (`factory:blocked`) rather than letting them
guess, so get this one right before moving on.

Key fields to get right on the first pass:

| Field | What happens if it's wrong |
|---|---|
| `branches.staging` | Task PRs target the wrong branch, or fail to find one that doesn't exist |
| `commands.test` / `build` / `lint` | Implementer/QA can't verify their own work; use `null` for gates this repo doesn't have |
| `estate_role` | Planner can't derive cross-repo merge order |
| `deploy.health_checks` | Must be runnable commands (`curl -fsS ...`), not descriptions |

## 4. Copy the config and caller-stub files

Seven files land in the consuming repo, none of them logic — just triggers,
version pins and per-repo data (FACTORY.md §10). Copy each from `templates/`
in this repo and adjust as noted.

| Destination | Source template | Adjust |
|---|---|---|
| `.github/workflows/factory-pipeline.yml` | `templates/workflows/factory-pipeline.yml` | Owner in the `uses:` ref if you forked the factory |
| `.github/workflows/factory-branch-guard.yml` | `templates/workflows/factory-branch-guard.yml` | Same |
| `.github/factory-models.json` | `templates/factory-models.json` | Optional — retune the model preference chain per role |
| `.github/factory-approvers.json` | `templates/factory-approvers.json` | Required — replace `genai-jerry` with real GitHub usernames per gate |
| `.github/factory-release.json` | `templates/factory-release.json` | Optional — release gating. Omit the file and a filed issue goes straight to intake |
| `.claude/settings.json` | `templates/settings.json` | Merge into an existing file if one is present; keep the `permissions.deny` block — it's half of gate G3 |

```bash
mkdir -p .github/workflows .claude
cp /path/to/claude-software-factory/templates/workflows/factory-pipeline.yml .github/workflows/
cp /path/to/claude-software-factory/templates/workflows/factory-branch-guard.yml .github/workflows/
cp /path/to/claude-software-factory/templates/factory-models.json .github/
cp /path/to/claude-software-factory/templates/factory-approvers.json .github/
cp /path/to/claude-software-factory/templates/factory-release.json .github/   # optional
cp /path/to/claude-software-factory/templates/settings.json .claude/
```

Notes:

- `factory-approvers.json` ships with a placeholder username in every gate —
  edit it before merging, or every gate defaults to "any collaborator may
  approve," which is probably not what you want.
- `factory-release.json` is the release gate (FACTORY.md §2d). With it in
  place, a filed issue is parked in `factory:backlog` until the milestone it
  belongs to is approved at gate G0 — so create a milestone and set it on the
  issue, or nothing will run. Its `release_scope` approvers come from
  `factory-approvers.json`. Set `"approval": "agent"` to let the Scrum Master's
  own GO verdict open G0 instead of a person.
- `.claude/settings.json`'s `_doc` key documents itself; delete it before
  committing if you'd rather not carry commentary in a settings file.
- **The caller stubs must declare `permissions:` themselves.** A called
  workflow's token is capped by the caller's, so a stub missing that block
  inherits the repo default and fails at startup before any job runs. The
  templates already carry the right blocks — keep them if you edit a stub.

## 5. Add repository secrets

Settings → Secrets and variables → Actions → **Repository secrets** (not
Environment secrets — those don't reach jobs that skip `environment:`, which
is the most common first-run failure):

- `ANTHROPIC_API_KEY`, **or** `CLAUDE_CODE_OAUTH_TOKEN` from
  `claude setup-token` if billing through a Claude subscription. One of the
  two is required; the workflow fails with a clear message if both are
  missing.
- `FACTORY_CROSS_REPO_TOKEN` — only if this repo participates in multi-repo
  epics. A fine-grained PAT with Issues + Contents + Pull requests on every
  repo in the estate. Without it, cross-repo stages fall back to the
  single-repo workflow token and apply `factory:blocked` when an epic needs
  access outside this repo.

## 6. Merge the stubs to the default branch

GitHub only fires workflow files that physically exist on the repo's
**default branch** — the four `.github/*` and `.claude/settings.json` files
from step 4 must land there before any event triggers them.

To pilot the factory *before* merging to default, use the test harness stub
instead:

```bash
cp /path/to/claude-software-factory/templates/workflows/factory-test.yml .github/workflows/
```

Replace `<dev-branch>` inside it with your factory development branch, push
that branch, then trigger a stage by editing
`.github/factory-test-request.json` (see `templates/factory-test-request.json`
for the shape) and pushing again. Set `"role"` back to `"none"` afterwards,
and delete `factory-test.yml` once the pipeline stub is live on default —
it's pilot-only.

## 7. Install the plugin (once per machine)

The eleven role prompts, the handbook and the protected-branch hook are not
delivered by the files above — they come from the Claude Code plugin, and CI
doesn't need this step at all (the reusable workflows clone the factory repo
directly). Each **local machine** that will run `/factory:*` commands needs:

```bash
claude plugin marketplace add genai-jerry/claude-software-factory
claude plugin install factory@genai-jerry
```

The `extraKnownMarketplaces` / `enabledPlugins` keys already copied into
`.claude/settings.json` in step 4 record the intent but do **not** install on
their own — verified: with only those keys present and no prior install,
`/factory:*` does not load.

To try it without installing, point a session at a local checkout instead:

```bash
claude --plugin-dir /path/to/claude-software-factory
```

## 8. Verify the install

- `claude plugin validate /path/to/claude-software-factory` if developing the
  factory itself; otherwise open a session and confirm `/factory:intake` etc.
  are available.
- File a throwaway issue on the consuming repo and confirm the pipeline
  auto-applies `factory:intake` and the Intake Analyst runs (Actions tab →
  "Factory pipeline"). With release gating on, expect `factory:backlog`
  instead: create a milestone, add the issue to it, comment `Plan release` on
  the `release(...)` tracker the pipeline opened, then `Approved` on it — the
  issue should move to `factory:intake` and intake should run.
- Push a commit directly to `main`/`master` in a scratch repo (or check the
  hook's own tests) to confirm `hooks/protect-branches.py` blocks it — see
  FACTORY.md §8a for what's covered.
- Confirm `factory-branch-guard.yml` is enabled — it opens a
  `factory:incident` issue if a commit ever lands on `main` without a PR.

### A stage that "succeeds" but leaves the epic where it was

The `agent` job guards against this itself. It snapshots the issue's comment
count and `factory:*` state label before running the role and re-reads them
after; if neither moved, the step fails with

```
Role 'intake' finished but changed nothing on #16 - no factory:* label change
and no new comment. 13 tool permission denial(s) were recorded - the
--allowedTools list in this workflow is the likely cause.
```

The trace it requires is "label moved **or** a comment was posted", not "label
moved" — a role may legitimately decline to advance an issue (intake
recommending `factory:fast-track`, any role applying `factory:blocked`), but it
always says so on the issue first. A run that says nothing did nothing.

The usual cause is a role denied its tools. A headless run has no one to answer
a permission prompt, so every tool that isn't explicitly allowed is refused —
the role reads the repo, fails to run `gh` or write files, and exits cleanly.
`claude-code-action` still exits 0, which is why the guard exists.

The reusable pipeline passes the allow-list itself
(`--permission-mode acceptEdits --allowedTools "Bash,Read,Write,..."`), so this
only bites a fork that trimmed those flags, or a repo whose
`.claude/settings.json` adds a `permissions.deny` entry covering `Bash`. The
denial count in the error line confirms it; for the full picture re-run with
`show_full_output: true` on the `Run factory role` step.

### A comment that should have started something, and didn't

Commenting `Approved` only does something in four states —
`factory:release-ready` (gate G0, on a release tracker), `factory:spec-ready`
(gate G1), `factory:design-ready` (gate G2) and `factory:ready` (starts a task's
implementer). From anywhere else the router now replies saying so rather than
finishing green and silent. Same for a reply on a `factory:blocked` issue whose
stage has no automatic resume step.

## 9. Nothing to configure on GitHub itself

Branch protection needs a paid plan on private repos, so gate G3 (humans
merge to `main` via the UI) is enforced entirely by the hook, the permission
deny list and the branch guard from step 4 — see FACTORY.md §8a. If the repo
later moves to a plan with branch protection or rulesets, turn them on too
(require 1 approval + green CI on `main` and `staging`); the factory's own
controls then become defence-in-depth rather than the primary enforcement.

## Footprint summary

Everything a consuming repo holds, once setup is done:

```
.factory/profile.json                        # step 3 — the only genuinely-yours file
.github/workflows/factory-pipeline.yml        # step 4
.github/workflows/factory-branch-guard.yml    # step 4
.github/factory-models.json                   # step 4
.github/factory-approvers.json                # step 4
.github/factory-release.json                  # step 4 — optional (release gating)
.claude/settings.json                         # step 4
```

Seven files, none of them logic. The pipeline body, the eleven role prompts and
the protected-branch hook all stay in `claude-software-factory` and are
pulled in at run time.
