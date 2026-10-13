# Repository settings for open-source maintenance

Some protections live in files in this repo: `CODEOWNERS`, the issue and PR
templates, `dependabot.yml`, the CodeQL workflow, and the guard on the factory
pipeline that ignores issues from people without write access. The rest are
repository settings, which can't be committed. Apply them once, in
**Settings**, before making the repository public.

## Before you flip it to public

- [ ] Search the history for secrets. GitHub's secret scanning (below) covers
      known token formats. For anything else, run
      `gitleaks git` or `trufflehog git file://.` locally.
- [ ] Check that no deployment hostnames, IPs or personal data are in files
      you don't want public.
- [ ] Rotate any credential that was ever committed, even briefly. Deleting
      it from history is not enough once it has been pushed.

## General

- [ ] **Features:** Issues on. Discussions optional. Wiki off unless you use it.
- [ ] **Pull requests:** allow squash merging. Turn on
      *Always suggest updating pull request branches* and
      *Automatically delete head branches*.

## Rules → Rulesets → New branch ruleset (target: `main`)

- [ ] Restrict deletions
- [ ] Block force pushes
- [ ] Require a pull request before merging
  - [ ] Required approvals: **1**
  - [ ] Dismiss stale pull request approvals when new commits are pushed
  - [ ] Require review from Code Owners
  - [ ] Require conversation resolution before merging
- [ ] Require status checks to pass: add the CodeQL `Analyze` jobs once they
      have run at least once. *Routing conformance* only runs when routing
      files change, so don't make it required: a PR that doesn't trigger it
      would wait forever.
- [ ] Bypass list: add the **Repository admin** role with mode
      *For pull requests only*. GitHub doesn't let you approve your own PR,
      so a solo maintainer needs this to merge their own changes. They still
      have to go through a PR, and contributors still need your approval.

Consuming repos run whatever the `v1` branch points at. Give it its own
ruleset that at least blocks force pushes and deletion, so it can only move
forward. Add a tag ruleset that blocks deleting or moving release tags.

Rulesets are free on public repositories. They back up the factory's own
guardrails (protected-branch hook, deny list, branch-guard workflow) with a
control the server enforces.

## Actions → General

- [ ] **Fork pull request workflows from outside collaborators:**
      *Require approval for all outside collaborators*.
- [ ] **Workflow permissions:** *Read repository contents and packages
      permissions*. Every workflow that needs more declares it in its own
      `permissions:` block.
- [ ] **Allow GitHub Actions to create and approve pull requests:** leave on
      only if the factory opens PRs with the workflow token in this repo.
      Turn it off otherwise.

## Environments

- [ ] For each deploy environment (for example `production`), add
      **Required reviewers** (the maintainer) and restrict
      **Deployment branches** to `main`. Environment secrets are then never
      exposed to a workflow run from a fork or a feature branch.

## Secrets

- [ ] Keep API keys (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`,
      `FACTORY_CROSS_REPO_TOKEN`) as repository or environment **secrets**,
      never variables. Workflows triggered by `pull_request` from forks do not
      receive them. Never add a `pull_request_target` workflow that checks out
      the PR's code.

## Code security

- [ ] Private vulnerability reporting: **on** (SECURITY.md links to it)
- [ ] Dependency graph and Dependabot alerts: **on**
- [ ] Dependabot security updates: **on**
- [ ] Secret scanning and **push protection**: **on**
- [ ] Code scanning: the CodeQL workflow in `.github/workflows/codeql.yml`
      covers it. Don't also enable *default setup*, or the two will conflict.

## Moderation

- [ ] **Moderation options → Interaction limits:** use temporarily if the
      repo attracts spam.
- [ ] **Code review limits:** optionally limit approvals to users with write
      access.
