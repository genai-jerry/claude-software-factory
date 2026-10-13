# Security Policy

The factory runs AI agents with write access to your repositories, so its
guardrails are its most important feature. We treat any way around them as a
vulnerability.

## Supported versions

| Ref | Supported |
|---|---|
| `v1` (the ref consuming repos pin) | ✅ |
| `main` | ✅ |
| Older tags (`v0.1`) | ❌ |

## Reporting a vulnerability

**Please do not report security issues in public issues, discussions or pull
requests.**

Report privately through GitHub instead:
**[Security → Report a vulnerability](https://github.com/genai-jerry/claude-software-factory/security/advisories/new)**.

Please include the component (role prompt, hook, reusable workflow,
orchestrator), the factory ref, steps to reproduce, and the impact you think it
has.

What to expect:

- an acknowledgement within **3 business days**;
- an initial assessment within **10 business days**;
- credit in the advisory once a fix ships, unless you prefer not to be named.

## In scope

- Any way an agent can get a commit onto `main` (or the default branch)
  without a human merge: hook bypasses, refspec forms the hook misses, merge
  tools that escape the deny list.
- Ways an untrusted person (no write access) can start an agent run, pass a
  gate, or approve on someone else's behalf.
- Issue, comment or file content that makes an agent leak secrets or act
  beyond its role (prompt injection with a concrete escalation).
- Workflow token or secret exposure in the reusable workflows.
- Orchestrator issues: webhook signature bypass, `DISPATCH_TOKEN` bypass, token
  leakage in logs or run transcripts.

## Out of scope

- Behaviour that needs an attacker who already has write access to the
  consuming repo.
- Misconfigurations the docs warn against, such as `"*"` in an allowed-bots
  list on a public repo, or Actions secrets stored as plain variables.
- Vulnerabilities in GitHub, Claude Code or OpenSpec themselves. Report those
  upstream.

## Running it safely on a public repository

- Keep the issue-author guard in your copy of
  `templates/workflows/factory-pipeline.yml`. It stops issues from people
  without write access from starting agents.
- Store `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and
  `FACTORY_CROSS_REPO_TOKEN` as secrets. Never add a `pull_request_target`
  workflow that checks out PR code.
- Turn on branch rulesets for the default branch as well. They are free on
  public repos and back up the factory's own guardrails. See
  [.github/REPOSITORY_SETTINGS.md](.github/REPOSITORY_SETTINGS.md).
