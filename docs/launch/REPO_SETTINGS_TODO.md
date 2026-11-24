# Repo settings to do before launch

These are the things only the repository owner can do. None of them can be
committed, so they are listed here to tick off before the public launch
(Show HN, Reddit, dev.to). The security settings are in
[`.github/REPOSITORY_SETTINGS.md`](../../.github/REPOSITORY_SETTINGS.md); this
list only covers how the repo looks to a first-time visitor.

## About box (repo home page → the gear next to "About")

- [ ] **Description.** The current text says nine agent roles. The repo ships
      thirteen. Suggested text (GitHub allows 350 characters):

  > Delivery pipeline for Claude Code. A GitHub issue goes in; a specced,
  > reviewed, tested and released change comes out. 13 agent roles, human
  > approval gates, and no agent can push to main. Claude Code plugin plus
  > reusable GitHub Actions workflows.

- [ ] **Website.** Point it at the page a new visitor should read next. Until
      there is a landing page or a demo video, use the setup guide:
      `https://github.com/genai-jerry/claude-software-factory/blob/main/docs/setup-guide.md`
- [ ] **Topics.** Add these twelve (GitHub allows twenty):
      `claude-code`, `claude-code-plugin`, `ai-agents`, `agentic-workflow`,
      `openspec`, `github-actions`, `software-factory`,
      `spec-driven-development`, `langgraph`, `anthropic`, `developer-tools`,
      `ai-coding`
- [ ] Leave **Releases** ticked in the About box so the tagged release shows
      on the home page.

## Social preview (Settings → General → Social preview)

- [ ] Upload an image, 1280×640 px, under 1 MB. It is what Hacker News,
      Reddit, Slack and X show when the link is shared. Keep it plain: the
      name, the one-line description, and the pipeline stages. Without it,
      GitHub shows a generated card with the old About text.

## Discussions (Settings → General → Features)

- [ ] Turn **Discussions** on. Launch visitors ask questions that are not
      bugs, and without Discussions they either open an issue or leave.
- [ ] Create two pinned threads: "Show your setup" and "Questions".
- [ ] Add a Discussions link to `.github/ISSUE_TEMPLATE/config.yml` under
      `contact_links`, so question-askers are sent there from the issue menu.

## A tagged release (Releases → Draft a new release)

The repo has a `v0.1` tag and a `v1` **branch**. Consuming repos pin the
branch. There is no release a visitor can see on the home page.

- [ ] Pick the version. The plugin manifest says `0.2.0`. Either tag `v0.2.0`,
      or bump `.claude-plugin/plugin.json` and `marketplace.json` to `1.0.0`
      first and tag `v1.0.0`. Do **not** create a tag named `v1`: it would
      share a name with the branch that consuming repos pin, and git would
      treat the ref as ambiguous.
- [ ] Write release notes a stranger can read: what it does, what is in the
      box (13 roles, hook, reusable workflows, orchestrator), how to install
      (link the setup guide), and the known limits.
- [ ] Tick **Set as the latest release**.

## Your GitHub profile

- [ ] Pin both repos on `github.com/genai-jerry`: `claude-software-factory`
      first, `software-factory-view` (Compass) second.

## Compass (`software-factory-view`)

- [ ] Give it the same treatment: About text, topics, social preview.
      Suggested About text:

  > Compass: the optional web app for the Claude Software Factory. Set up
  > a repo, see where every piece of work is, and approve gates from a
  > browser or a phone.

- [ ] Put the hero repo's URL in Compass's **Website** field, so the two link
      to each other from the About box.

## Small things the launch PR could not change

The PR that added this file only touched docs. These need a maintainer:

- [ ] `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` still
      say "ten agent roles" and "four approval gates". The handbook describes
      thirteen roles and five gates (G0, G1, G2, GS, G3). Starter issue 4 in
      [`STARTER_ISSUES.md`](STARTER_ISSUES.md) covers it.
- [ ] Record the 60–90 second demo and replace the TODO line at the top of
      the README.
- [ ] File the starter issues in [`STARTER_ISSUES.md`](STARTER_ISSUES.md) and
      label them `good first issue`. GitHub lists that label on the repo's
      `/contribute` page.
