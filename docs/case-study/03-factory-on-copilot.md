# Running the Factory on GitHub Copilot

Version 1.0 · How the Lighthouse Software Factory maps onto Copilot's
customisation surfaces, what ports cleanly, and what does not

## 1. Why most of it ports

The factory was deliberately built so that its two foundations are
**vendor-neutral**:

- **State** lives in GitHub — issues, sub-issues, `factory:*` labels,
  milestones, PRs. No AI vendor is involved in knowing where work stands.
- **Content** lives in OpenSpec change folders — plain Markdown committed to
  the repo. Any agent that can read files can read a proposal, a spec scenario
  or a design.

Only the **execution layer** is Claude-specific: the role prompt format
(`.claude/commands/`), the launch mechanism (`anthropics/claude-code-action`),
and the permission guardrails (`.claude/settings.json`, the PreToolUse hook).
Roughly 70% of the factory — conventions, artifacts, labels, gates, workflows,
notification and approver logic — is unchanged by a switch to Copilot. What
must be rewritten is how an agent is *defined* and *invoked*.

## 2. Copilot's customisation surfaces

| Surface | File | Applies to | Invocation |
|---|---|---|---|
| Repo-wide instructions | `.github/copilot-instructions.md` | All Copilot surfaces in the repo | Automatic |
| Agent instructions | `AGENTS.md` (repo root) | Copilot coding agent | Automatic |
| Path-scoped instructions | `.github/instructions/*.instructions.md` (`applyTo:` glob frontmatter) | Files matching the glob | Automatic |
| Prompt files | `.github/prompts/*.prompt.md` (frontmatter: `description`, `mode`/`agent`, `model`, `tools`) | IDE chat — VS Code, Visual Studio, JetBrains | `/name` slash command |
| Custom agents | `.github/agents/*.agent.md` (frontmatter: name, description, tools, MCP servers) | Coding agent, VS Code chat, Copilot CLI | Selected by name / assignment |
| Agent skills | `SKILL.md` folders | Agents that support skills | Model-invoked by description |
| Coding agent | — | Issues assigned to Copilot | Assign issue → `copilot/*` branch → draft PR |
| Code review | — | Pull requests | Automatic or requested |

A useful accident: **three of the four Lighthouse repos already have an
`AGENTS.md`** describing their stack, commands and gotchas. Copilot's coding
agent reads that file natively, so per-repo conventions transfer for free.

## 3. The mapping

| Factory artifact | Copilot equivalent | Notes |
|---|---|---|
| `FACTORY.md` conventions | `.github/copilot-instructions.md` (or a pointer to `FACTORY.md` from it) | Repo-wide, every surface |
| Per-repo stack rules (`CLAUDE.md`) | `AGENTS.md` — already present | No work needed |
| Epic role prompts (intake, planner, architect…) | `.github/agents/factory-intake.agent.md` etc. | One agent file per role, body ported almost verbatim |
| Same roles for IDE use | `.github/prompts/factory-intake.prompt.md` | Lets a developer run a stage manually with `/factory-intake` |
| OpenSpec skills | Unchanged — the `openspec` CLI is tool-agnostic | Run `openspec init --tools github-copilot` to install Copilot-shaped commands |
| `factory-models.json` | Partially — see §5 | Copilot model choice is coarser |
| `factory-approvers.json` | Unchanged | Pure GitHub API logic in the workflow |
| Label state machine, gates G1–G3 | Unchanged | Plain GitHub |
| `factory-branch-guard.yml` | Unchanged | Plain GitHub |
| `.claude/settings.json` deny list + hook | Replaced by Copilot's own permission model | See §5 |

Role prompt bodies port with almost no editing — they are structured as
*trigger → mission → numbered steps → guardrails*, which is exactly the shape
Copilot agent and prompt files expect. The frontmatter changes; the content
does not.

## 4. Three ways to invoke agents

**Option A — Copilot coding agent (most native).** The pipeline workflow, on
each label transition, assigns the issue to Copilot with additional
instructions naming the role. Copilot acknowledges with 👀, creates a
`copilot/*` branch, opens a draft PR, works in an ephemeral Actions-powered
environment, pushes commits, then requests review. Environment setup (Node,
Python, DB services) is declared in a `copilot-setup-steps.yml` workflow.
*Best for:* implementer, reviewer, QA — stages whose natural output is a PR.

**Option B — Copilot CLI in Actions.** Keep `factory-pipeline.yml` structurally
identical and swap the agent step for the Copilot CLI with a custom agent
selected by name. This preserves per-stage routing, the model-probe pattern and
the harness. *Best for:* intake, planner, architect, dispatch, ops — stages
that write documents or manipulate GitHub state rather than produce a feature
branch.

**Option C — GitHub Agentic Workflows (`gh-aw`).** Compiles Markdown workflow
definitions into Actions workflows with a Copilot cloud-agent engine. Closest
to a drop-in replacement for the orchestration layer, at the cost of a new
dependency.

A hybrid of A and B mirrors the current design most faithfully: document stages
via CLI, code stages via the coding agent.

## 5. Gaps and mitigations

**Branch and PR conventions.** The coding agent owns its branch naming
(`copilot/*`) and opens its own PR against the branch it was started from. Our
`factory/<task>-<slug>` convention and the "implementation PRs base on
`staging`" rule cannot be dictated to it directly.
*Mitigation:* pass the base branch when assigning; relax the naming convention
for Copilot-authored branches and rely on the PR→issue link (which the coding
agent creates automatically) for traceability.

**Per-stage model routing.** `factory-models.json` currently probes a chain and
picks the best reachable model per role — Fable for judgement, Opus for volume,
Haiku for mechanical work. Copilot exposes model choice more coarsely (prompt
files accept a `model` field; the coding agent's selection is governed by
policy and plan).
*Mitigation:* keep the config file as documentation of intent, apply `model:`
in prompt files where supported, and accept a single tier for coding-agent
stages.

**Permission guardrails.** The PreToolUse hook and merge-tool deny list are
Claude Code mechanisms and have no direct analogue.
*Mitigation:* Copilot's model is arguably stronger here — the coding agent
cannot push to protected branches, its PRs require human approval before
workflows run, and it cannot approve its own PR. Keep `factory-branch-guard.yml`
as the detection net; gate G3 remains a human merge click either way.

**Independent review.** Our Reviewer is deliberately a *different model* from
the Implementer, so blind spots differ.
*Mitigation:* combine Copilot code review on the PR with a factory reviewer
agent run; or keep the Reviewer stage on Claude in a hybrid estate.

**Prompt file reach.** Prompt files are IDE-only (VS Code, Visual Studio,
JetBrains) — they do not drive the coding agent. Custom agent files are the
coding-agent-facing equivalent.
*Mitigation:* maintain both for the roles a developer might run by hand; the
body is shared, so this is copy-not-rewrite.

## 6. Migration path

1. **Port conventions.** Add `.github/copilot-instructions.md` pointing at
   `FACTORY.md` and stating the one rule (issues carry state, change folders
   carry content). `AGENTS.md` already covers per-repo stacks.
2. **Port one role.** Convert the Reviewer to `.github/agents/factory-reviewer.agent.md`
   and run it on a real PR alongside the Claude reviewer. Compare findings —
   this is the cheapest, highest-signal comparison available.
3. **Port the document stages** (intake, planner, architect) as custom agents
   invoked by the existing pipeline via Copilot CLI. Labels, gates, approvers
   and notifications need no changes.
4. **Port implementation** by assigning `factory:ready` task issues to the
   coding agent, with the change folder path in the assignment instructions.
5. **Decide the steady state:** all-Copilot, all-Claude, or hybrid by stage.

Because state and artifacts are shared, **a hybrid estate is genuinely
workable** — the Architect could be Claude and the Implementer Copilot on the
same epic, since both read the same `design.md` and write to the same labels.
That optionality was the point of keeping the artifact layer plain Markdown.

## 7. Effort estimate

| Work | Scale |
|---|---|
| `copilot-instructions.md` + instruction files | ~1 hour |
| Convert 9 role prompts to `.agent.md` + `.prompt.md` | ~half a day (bodies port verbatim) |
| Swap the pipeline's agent step (CLI or assignment) | ~half a day |
| `copilot-setup-steps.yml` per repo | ~2 hours |
| Re-pilot one epic end to end | ~1 day |

Roughly **two to three days** to reach the state the Claude-based factory is in
today — the difference being that the conventions, artifacts, labels, gates and
guardrails are already designed, proven and portable.

---

**Sources:** [Copilot coding agent docs](https://docs.github.com/en/copilot/concepts/coding-agent) ·
[About custom agents](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-custom-agents) ·
[Creating custom agents for Copilot cloud agent](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/create-custom-agents) ·
[awesome-copilot agents guide](https://github.com/github/awesome-copilot/blob/main/docs/README.agents.md) ·
[Prompt files in VS Code](https://code.visualstudio.com/docs/agent-customization/prompt-files) ·
[Assigning issues to coding agent](https://github.blog/ai-and-ml/github-copilot/assigning-and-completing-issues-with-coding-agent-in-github-copilot/) ·
[GitHub Agentic Workflows](https://github.github.com/gh-aw/reference/copilot-cloud-agent/)
