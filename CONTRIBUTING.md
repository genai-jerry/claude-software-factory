# Contributing to the Claude Software Factory

Thanks for helping. The factory is a set of role prompts, a handbook, reusable
GitHub Actions workflows and a LangGraph orchestrator. Bug reports, fixes, docs
and well-scoped features are all welcome. A report from a real deployment that
broke is especially valuable.

## Before you start

- **Bugs:** file a [bug report](https://github.com/genai-jerry/claude-software-factory/issues/new?template=bug_report.yml).
  Include the role, the engine (Actions or orchestrator), and the factory ref
  you pin.
- **Features and behaviour changes:** open a
  [feature request](https://github.com/genai-jerry/claude-software-factory/issues/new?template=feature_request.yml)
  first. Anything that changes routing, labels or gates changes a contract that
  consuming repos and the [Compass](https://github.com/genai-jerry/software-factory-view)
  rely on, so agree on the approach before writing code.
- **Security issues** (hook bypasses, ways an agent could reach `main`, token
  exposure, prompt injection that escalates access): do **not** open a public
  issue. See [SECURITY.md](SECURITY.md).

Larger changes are planned as OpenSpec changes under `openspec/changes/`.
Look there, and at [FACTORY.md](FACTORY.md), before proposing one.

## Repository layout

| Path | What it is | How to test it |
|---|---|---|
| `commands/` | 13 role prompts (`/factory:<role>`) | Run the role locally with `claude --plugin-dir .` |
| `FACTORY.md`, `handbook/` | The handbook and the hand-off table | `orchestrator/tests/test_next_step.py` |
| `hooks/` | Protected-branch PreToolUse hook | Feed it `git push` payloads by hand, see [FACTORY.md §8a](FACTORY.md) |
| `.github/workflows/factory-pipeline.yml` | Reusable pipeline, including the JS router | `node scripts/test-router.js` |
| `orchestrator/` | LangGraph engine (Python 3.11+) | `make test` |
| `orchestrator/conformance/` | Routing fixtures both engines must pass | `make conformance` |
| `templates/` | Files consuming repos copy | Pilot with `templates/workflows/factory-test.yml` |

## Development setup

You need Python 3.11+, Node.js 20.19+, and git. Docker is optional.

```bash
git clone https://github.com/<you>/claude-software-factory.git
cd claude-software-factory

# Orchestrator
cd orchestrator
make install       # creates ./.venv
make test          # full suite, including the shared routing fixtures
make lint          # ruff
make conformance   # both routers against the fixtures (needs node + js-yaml)
cd ..

# Actions router on its own
npm install --no-save js-yaml
node scripts/test-router.js
```

## Rules for changes

- **The two routers must agree.** A change to the JS router in
  `factory-pipeline.yml` needs the same change in the Python router, plus a
  fixture in `orchestrator/conformance/fixtures/`. The *Routing conformance*
  workflow fails otherwise.
- **Role prompts are byte-identical everywhere.** Anything repo-specific
  belongs in `.factory/profile.json`, not in a prompt.
- **Guardrails are controls, not instructions.** Never weaken the
  protected-branch hook, the permission deny list or the branch guard without
  a test that shows the new behaviour, and a reason in the PR.
- **Contracts are public.** Label names, comment controls (`Approved`,
  `Plan release`, …) and hidden markers are read by consuming repos and the
  Console. Renaming one is a breaking change. Call it out in the PR.
- **Docs move with code.** If behaviour changes, update `FACTORY.md` and, where
  relevant, `docs/setup-guide.md` and the templates.

## Pull requests

- Keep each PR focused on one change.
- Fill in the PR template and link the issue it closes.
- All checks must pass, and a code owner must approve, before merge.
- Consuming repos pin a ref (`v1`). Maintainers move that ref when a release is
  cut, so don't edit it in a PR.
- By contributing, you agree that your contribution is licensed under the
  [MIT License](LICENSE).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By taking
part, you agree to uphold it.
