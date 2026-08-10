# Software Factory

An agent-driven delivery pipeline for Claude Code. A plain GitHub issue goes in;
a specced, planned, designed, implemented, reviewed, tested and released change
comes out — with human approval gates and no ability for an agent to put
anything on `main`.

Two foundations, one rule:

- **GitHub is the state machine.** Milestones are releases; issues, sub-issues
  and `factory:*` labels encode *where* work is. Labels trigger agents.
- **[OpenSpec](https://github.com/Fission-AI/openspec) is the content.** *What*
  is being built — proposal, WHEN/THEN scenarios, design, task list — lives in
  `openspec/changes/<issue>-<slug>/`.
- **The rule:** issues carry state plus a link, never spec content. That is what
  stops the two sources of truth from drifting.

Ten roles move work between them: scrum → intake → planner → architect →
dispatch → implementer → reviewer → qa → release → ops.

**[FACTORY.md](FACTORY.md) is the handbook.** Everything below is how to install
it. For a step-by-step walkthrough of every install step, see
[`docs/setup-guide.md`](docs/setup-guide.md).

## Releases, not a firehose

By default a filed issue starts an agent immediately. Turn on **release gating**
(`.github/factory-release.json`) and it doesn't: the issue waits in
`factory:backlog` until the GitHub milestone it belongs to — the milestone *is*
the release — is approved at gate G0. A **Scrum Master** role reads the whole
milestone first and posts a release plan: scope, sequencing between issues,
duplicates, oversized items, GO or NO-GO. Approving it starts every issue in the
release at once. Handbook: [FACTORY.md §2d](FACTORY.md).

## What is repo-specific, and what isn't

The eleven role prompts are byte-identical everywhere. Everything a role needs to
know about *your* codebase — stack, test/build/lint commands, conventions,
review checklist, known-failing tests, health checks — lives in one data file,
`.factory/profile.json`. Pointing the factory at a new project means writing
that file, not rewriting prompts.

## Install

Requires Node 20.19+ and a repo you can add Actions secrets to.

```bash
# 1. Labels
GITHUB_TOKEN=<token> bash scripts/setup-labels.sh <owner> <repo>

# 2. OpenSpec (the factory depends on it; it is not vendored here)
cd /path/to/your/repo
npx -y @fission-ai/openspec@latest init --tools claude

# 3. Profile — the only file whose contents are genuinely yours
mkdir -p .factory
curl -o .factory/profile.json \
  https://raw.githubusercontent.com/genai-jerry/claude-software-factory/v1/templates/profile.example.json
$EDITOR .factory/profile.json        # replace every value

# 4. Config + caller stubs (copy from templates/, adjust owner and refs)
#    .github/workflows/factory-pipeline.yml
#    .github/workflows/factory-branch-guard.yml
#    .github/factory-models.json
#    .github/factory-approvers.json
#    .github/factory-release.json      # optional — release gating (FACTORY.md §2d)
#    .claude/settings.json

# 5. Plugin (once per machine; CI does not need it)
claude plugin marketplace add <owner>/claude-software-factory
claude plugin install factory@<owner>
```

Then add `ANTHROPIC_API_KEY` **or** `CLAUDE_CODE_OAUTH_TOKEN` as a
**repository** secret — Settings → Secrets and variables → Actions. Environment
secrets do not reach jobs that don't declare `environment:`; that is the most
common first-run failure. For a multi-repo estate add `FACTORY_CROSS_REPO_TOKEN`
(a fine-grained PAT with Issues + Contents + Pull requests on every repo).

The caller stubs must be on your **default branch** before GitHub will fire
them. To pilot the factory before merging them there, use the test harness stub
(`templates/workflows/factory-test.yml`) — it runs from a development branch.

That's the whole footprint: eight files, none of them logic. The pipeline body,
the role prompts and the hook stay in this repo.

## Why two channels

GitHub only runs workflow files that physically exist in the repo being built,
so a Claude Code plugin cannot deliver them. Hence:

| Channel | Delivers |
|---|---|
| Claude Code plugin `factory` | 11 role prompts, the handbook, the protected-branch hook |
| Reusable Actions workflows | the pipeline, the branch guard, the pilot harness |

Both serve the same files from the same tagged commit — in CI the runner clones
this repo at `factory_ref` and injects the handbook and role prompt into the
agent's prompt directly.

## Local use

```bash
claude --plugin-dir /path/to/claude-software-factory
```

gives you `/factory:scrum` … `/factory:ops` and the protected-branch hook in
that session, without installing anything. To install it properly, the repo is
its own marketplace:

```bash
claude plugin marketplace add genai-jerry/claude-software-factory
claude plugin install factory@genai-jerry
```

`templates/settings.json` declares the marketplace and marks the plugin enabled
so the choice is recorded in the repo, but that is **not** a substitute for the
install: with only those keys present and no prior install, `/factory:*` does
not load. Each machine runs the two commands above once.

CI needs neither — the reusable workflows clone this repo directly.

## Guardrails

GitHub branch protection needs a paid plan on private repos, so the factory
enforces its own, in three layers:

1. A **PreToolUse hook** blocks any agent `git push` targeting `main`/`master`
   — every refspec form, force pushes, deletes, and bare `git push` while
   checked out on a protected branch.
2. A **permission deny list** removes the PR-merge tools from agent sessions
   entirely. Humans merge in the GitHub UI; that click is gate G3.
3. A **detection workflow** opens a `factory:incident` issue if a commit ever
   lands on `main` without a pull request.

Controls, not instructions. The hook is tested — see FACTORY.md §8a.

## Layout

```
commands/            11 role prompts       → /factory:<role>
hooks/               protect-branches.py + hooks.json
.github/workflows/   reusable pipeline, harness, branch guard
templates/           everything a consuming repo copies
scripts/             setup-labels.sh, publish-wiki.sh, test-router.js
docs/case-study/     the original four-repo deployment, written up
FACTORY.md           the handbook
```

## Who built this

The factory is written and maintained by [Jerry Kurian](https://www.linkedin.com/in/jerryk/)
([@genai-jerry](https://github.com/genai-jerry)) at [GenAI People](https://genaipeople.com).
It began as internal tooling, not as a product: the problem was a four-repository
estate where Claude Code could write good code but nothing could tell you *where*
a piece of work was, what it was supposed to do, or who had agreed to it. Issues
became the state, OpenSpec became the content, and the three human gates were what
made it safe to leave running.

That original deployment is written up in [`docs/case-study/`](docs/case-study/) —
what the pipeline does, what each role produces, and how it was ported to a second
agent runner.

Developed in the open under MIT. Issues and pull requests are welcome; if you
deploy it somewhere and something breaks, an issue saying so is worth more to the
next person than a star.

## License

MIT.
