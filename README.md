# Software Factory

[![Routing conformance](https://github.com/genai-jerry/claude-software-factory/actions/workflows/conformance.yml/badge.svg)](https://github.com/genai-jerry/claude-software-factory/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Software Factory is a delivery pipeline for teams that use Claude Code: it
turns a plain GitHub issue into a specced, reviewed, tested and released
change, with a person approving each gate and no agent able to put anything on
`main`.

⭐ Star this repo if it's useful. It helps other people find it.

Prefer a browser to labels and comments?
**[Compass](https://github.com/genai-jerry/software-factory-view)** is the
optional web app for setup, review and gate approvals.

<!-- TODO(Jerry): replace the line below with the 60-90 second demo video or GIF. -->
> **Demo:** _TODO. A 60-90 second walkthrough goes here (issue in, gates
> approved, promotion PR out). Not recorded yet._

## Try it in 5 minutes

Five minutes gets you a local look at the roles and the branch hook. Nothing is
installed, and nothing is written to your repository. You need git, Python 3
and [Claude Code](https://code.claude.com).

1. Clone the factory:

   ```bash
   git clone https://github.com/genai-jerry/claude-software-factory.git
   ```

2. Open Claude Code in any git repository, with the plugin loaded for that
   session only:

   ```bash
   claude --plugin-dir /path/to/claude-software-factory
   ```

3. Type `/factory:` to see the thirteen role commands. The protected-branch
   hook is active in the same session, so an agent `git push` to `main` or
   `master` is blocked.

Running the whole pipeline on a repository takes longer than five minutes. It
needs labels, OpenSpec, a repo profile, two workflow stubs, one secret and the
Claude GitHub App. Follow [`docs/setup-guide.md`](docs/setup-guide.md) step by
step, or let [Compass](https://github.com/genai-jerry/software-factory-view)
onboarding do most of it from the browser. The short version is under
[Install](#install).

## Why not just plain Claude Code?

Claude Code on its own writes good code. It does not tell you where a piece of
work is, what it was meant to do, or who agreed to it. The factory adds four
things:

- **Gates.** A person approves the spec (G1), the design (G2), the release to
  staging (GS) and the promotion to `main` (G3). With release gating on, a
  fifth gate (G0) approves a whole milestone. An epic marked
  `factory:expedite` skips the waiting before GS, but GS and G3 always need a
  person.
- **No agent on `main`.** A hook blocks agent pushes to `main`, a deny list
  removes the PR-merge tools from agent sessions, and a workflow raises an
  incident if a commit lands on `main` without a pull request.
- **Staging first.** Every implementation PR is based on your integration
  branch. The change is merged and checked there before the promotion PR is
  opened.
- **The spec is the source of truth.** What is being built lives in an
  [OpenSpec](https://github.com/Fission-AI/openspec) change folder. Issues
  carry state and a link, never spec content, so the two cannot drift.

For a one-off change in a small repository, plain Claude Code is the simpler
choice. The factory earns its setup when work has to pass through several
people and several steps.

## How it compares

- **Plain Claude Code, or `claude-code-action` on its own:** one agent session
  per request, and the process around it is yours to build. The factory runs
  on both and adds the states, the roles and the gates.
- **OpenSpec on its own:** gives you the spec format and the `/opsx:*`
  commands. The factory depends on it and adds the pipeline that carries a
  spec through to a release.
- **Hosted coding agents:** quicker to start. The factory runs in your own
  GitHub Actions, or on your own server, with your own key. Everything it does
  is an issue, a label, a comment or a pull request you can read.

Know the limits before you adopt it. It is young (plugin version 0.2.0) and
has one maintainer. It works with GitHub and Claude Code only. Setup takes
real effort, and every role run uses your Anthropic API key or Claude
subscription.

## What it is

An agent-driven delivery pipeline for Claude Code. A plain GitHub issue goes in.
A specced, planned, designed, implemented, reviewed, tested and released change
comes out, with human approval gates along the way and no way for an agent to
put anything on `main`.

Two foundations and one rule:

- **GitHub is the state machine.** Milestones are releases. Issues, sub-issues
  and `factory:*` labels encode *where* work is. Labels trigger agents.
- **[OpenSpec](https://github.com/Fission-AI/openspec) is the content.** *What*
  is being built (proposal, WHEN/THEN scenarios, design, task list) lives in
  `openspec/changes/<issue>-<slug>/`.
- **The rule:** issues carry state plus a link, never spec content. That keeps
  the two sources of truth from drifting.

There are thirteen roles. Ten move work along the main line: scrum → intake → planner → architect →
dispatch → implementer → reviewer → qa → release → ops. Three more run beside
it: the **Profiler** writes the repo profile, the **Fast-Track** role ships
small changes end to end, and the **Test Planner** turns an approved spec into
human-run system tests. Everything they build lands on a staging branch and is
proved there before a human promotes it to `main`.

**[FACTORY.md](FACTORY.md) is the handbook.** This README covers how to install
the factory. For a step-by-step walkthrough of every install step, see
[`docs/setup-guide.md`](docs/setup-guide.md).

> **Version:** plugin `factory` 0.2.0. Consuming repos pin the `v1` ref.
> **Web UI:** [Compass](https://github.com/genai-jerry/software-factory-view)
> handles setup, review and gate approvals in the browser. It's optional, since
> the factory is driven entirely through GitHub.

## Contents

- [Try it in 5 minutes](#try-it-in-5-minutes)
- [Why not just plain Claude Code?](#why-not-just-plain-claude-code)
- [How it compares](#how-it-compares)
- [What it is](#what-it-is)
- [Install](#install)
- [Two engines](#two-engines)
- [Local use](#local-use)
- [How it works](#how-it-works): releases, repo profile, two channels, guardrails, staging
- [Layout](#layout)
- [Contributing](#contributing) · [Security](#security) · [License](#license)

## Install

### Requirements

- A GitHub repository you can add Actions secrets to.
- Node.js 20.19+ (for OpenSpec and the label script).
- [Claude Code](https://code.claude.com) on any machine where you run roles by hand.
- An `ANTHROPIC_API_KEY`, or a `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`.
- The [Claude GitHub App](https://github.com/apps/claude) installed on that
  repository. Agent jobs use it to comment on issues and open PRs.

### Steps

Run these in the repository you want the factory to build. The full walkthrough
is in [`docs/setup-guide.md`](docs/setup-guide.md).

```bash
# 1. Labels
GITHUB_TOKEN=<token> bash /path/to/claude-software-factory/scripts/setup-labels.sh <owner> <repo>

# 2. OpenSpec (the factory depends on it; it is not vendored here)
npx -y @fission-ai/openspec@latest init --tools claude

# 3. Repo profile: the only file whose contents are genuinely yours.
#    Fill it in by hand, or let the Profiler draft it (file an issue labelled factory:profile).
mkdir -p .factory
curl -o .factory/profile.json \
  https://raw.githubusercontent.com/genai-jerry/claude-software-factory/v1/templates/profile.example.json

# 4. Config and caller stubs
F=/path/to/claude-software-factory/templates
mkdir -p .github/workflows .claude
cp $F/workflows/factory-pipeline.yml $F/workflows/factory-branch-guard.yml .github/workflows/
cp $F/factory-models.json $F/factory-approvers.json $F/factory-branches.json .github/
cp $F/settings.json .claude/
# optional: $F/factory-release.json  (release gating, FACTORY.md §2d)
#           $F/factory-testing.json  (system tests and bug reports, §4b/§4c)
$EDITOR .github/factory-approvers.json   # replace the placeholder usernames
```

5. **Add secrets.** Add `ANTHROPIC_API_KEY` **or** `CLAUDE_CODE_OAUTH_TOKEN` as
   a **repository** secret (Settings → Secrets and variables → Actions).
   Environment secrets don't reach jobs that don't declare `environment:`,
   which is the most common first-run failure. For a multi-repo estate, also
   add `FACTORY_CROSS_REPO_TOKEN`: a fine-grained PAT with Issues, Contents and
   Pull requests on every repo.
6. **Merge the stubs to your default branch.** GitHub only fires workflow files
   that exist there. To pilot from a development branch first, use the test
   harness stub (`templates/workflows/factory-test.yml`).
7. **Install the plugin** once per machine where you run roles by hand. CI
   doesn't need it:

   ```bash
   claude plugin marketplace add genai-jerry/claude-software-factory
   claude plugin install factory@genai-jerry
   ```

That's the whole footprint: a handful of config files and caller stubs, none of
them logic. The pipeline body, the role prompts and the hook stay in this repo
and are pulled in at run time.

> **Public repositories:** the template `factory-pipeline.yml` ignores issues
> opened by people without write access, so a stranger can't start an agent or
> spend your API budget. To adopt such an issue, apply `factory:fast-track` or
> run the workflow by hand with role `intake`. Keep this guard if you edit the
> stub.

Upgrading means moving the ref: consuming repos pin `factory_ref: v1` in their
caller stub, and the `v1` branch moves forward when a release is cut.

## Two engines

The same routing table runs on either engine. Shared fixtures in
[`orchestrator/conformance/`](orchestrator/conformance/) prove that both make
the same decisions.

| Engine | When to use it | Setup |
|---|---|---|
| **GitHub Actions** (default) | No infrastructure. Each event runs a workflow | The install above |
| **LangGraph orchestrator** | Long-lived service. Webhook-driven, runs roles in isolated workspaces, uses a GitHub App | [`orchestrator/README.md`](orchestrator/README.md). Opt a repo in with `.github/factory-orchestrator.json` (FACTORY.md §2e) |

To run the orchestrator and Compass together on a laptop, see
[`docs/run-locally.md`](docs/run-locally.md).

## Local use

```bash
claude --plugin-dir /path/to/claude-software-factory
```

This gives you `/factory:scrum` … `/factory:ops` and the protected-branch hook
in that session, without installing anything.

`templates/settings.json` declares the marketplace and marks the plugin enabled,
so the choice is recorded in the repo. That isn't a substitute for installing
it, though. With only those keys and no prior install, `/factory:*` doesn't
load. Each machine runs the two `claude plugin` commands above once.

## How it works

### Releases, not a firehose

By default, a filed issue starts an agent immediately. Turn on **release
gating** (`.github/factory-release.json`) and it doesn't. Instead, the issue
waits in `factory:backlog` until the GitHub milestone it belongs to is approved
at gate G0. The milestone *is* the release. A **Scrum Master** role reads the
whole milestone first and posts a release plan: scope, sequencing between
issues, duplicates, oversized items, and a GO or NO-GO verdict. Approving it
starts every issue in the release at once. Handbook:
[FACTORY.md §2d](FACTORY.md).

### What is repo-specific, and what isn't

The thirteen role prompts are byte-identical everywhere. Everything a role needs
to know about *your* codebase lives in one data file, `.factory/profile.json`:
stack, test, build and lint commands, conventions, review checklist,
known-failing tests and health checks. Pointing the factory at a new project
means writing that file, not rewriting prompts.

### Why two channels

GitHub only runs workflow files that physically exist in the repo being built,
so a Claude Code plugin can't deliver them. The factory therefore ships through
two channels:

| Channel | Delivers |
|---|---|
| Claude Code plugin `factory` | 13 role prompts, the handbook, the protected-branch hook |
| Reusable Actions workflows | the pipeline, the branch guard, the pilot harness |

Both serve the same files from the same tagged commit. In CI, the runner clones
this repo at `factory_ref` and injects the handbook and role prompt into the
agent's prompt directly.

### Guardrails

GitHub branch protection needs a paid plan on private repos, so the factory
enforces its own, in three layers:

1. A **PreToolUse hook** blocks any agent `git push` that targets `main` or
   `master`. That covers every refspec form, force pushes, deletes, and a bare
   `git push` while checked out on a protected branch.
2. A **permission deny list** removes the PR-merge tools from agent sessions
   entirely. Humans merge in the GitHub UI, and that click is gate G3.
3. A **detection workflow** opens a `factory:incident` issue if a commit ever
   lands on `main` without a pull request, or arrives through a PR that didn't
   come from the integration branch. Either one means a change reached `main`
   without being proved on staging.

These are controls, not instructions. The hook is tested; see FACTORY.md §8a.
On a public repository, also turn on GitHub's rulesets (free there) as defence
in depth. See [`.github/REPOSITORY_SETTINGS.md`](.github/REPOSITORY_SETTINGS.md).

### Staging first

Nothing the factory writes reaches `main` directly. Every implementation PR,
for tasks and fast-lane changes alike, is based on the org's **integration
branch**. That might be `staging`, `develop`, `qa` or whatever your estate calls
it, named once in `.github/factory-branches.json`. The Release Manager merges
the epic's PRs onto that branch in dependency order, watches the staging deploy,
and runs the repo's health checks after each one. Only then does it open one
promotion PR per repo for a human to merge. So gate G3 is a decision about a
build that already ran, not a hopeful read of a diff.

Two states carry this: `factory:ready-to-ship` (green, awaiting the integration
merge) and `factory:in-staging` (on staging and verified, promotion PR open,
awaiting G3). Document PRs (spec, design, profile) are the one exception. They
still merge straight to the default branch, because every later stage clones it.
Handbook: [FACTORY.md §6a](FACTORY.md).

## Layout

```
commands/            13 role prompts            → /factory:<role>
hooks/               protect-branches.py + hooks.json
handbook/            the hand-off table both engines render
.github/workflows/   reusable pipeline, harness, branch guard, conformance
orchestrator/        LangGraph engine (Python), conformance fixtures, deploy
templates/           everything a consuming repo copies
scripts/             setup-labels.sh, publish-wiki.sh, test-router.js
openspec/            this repo's own specs and changes
docs/                setup guide, local-run guide, case study
tools/               log-reader, a read-only log tool for Compass
wiki/                source for the GitHub wiki
FACTORY.md           the handbook
```

## Who built this

The factory is written and maintained by [Jerry Kurian](https://www.linkedin.com/in/jerryk/)
([@genai-jerry](https://github.com/genai-jerry)) at [GenAI People](https://genaipeople.com).
It began as internal tooling, not as a product. The problem was a
four-repository estate where Claude Code could write good code, but nothing
could tell you *where* a piece of work was, what it was supposed to do, or who
had agreed to it. Issues became the state, OpenSpec became the content, and the
human gates are what made it safe to leave running.

That original deployment is written up in [`docs/case-study/`](docs/case-study/):
what the pipeline does, what each role produces, and how it was ported to a
second agent runner.

## Contributing

The factory is developed in the open. Issues and pull requests are welcome. If
you deploy it somewhere and something breaks, an issue saying so is worth more
to the next person than a star.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, the rule that both
routers change together, and the PR checklist. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Guardrail bypasses and other vulnerabilities should be reported privately. See
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 genai-jerry
