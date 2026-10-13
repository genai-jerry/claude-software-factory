## What this changes

<!-- One or two sentences. What behaves differently for a consuming repo? -->

Closes #

## Why

<!-- The problem, or a link to the issue, FACTORY.md section or OpenSpec change. -->

## Engines and contracts touched

- [ ] Actions engine (`.github/workflows/factory-pipeline.yml`)
- [ ] LangGraph orchestrator (`orchestrator/`)
- [ ] Role prompts (`commands/`)
- [ ] Guardrails (hook, deny list, branch guard)
- [ ] Public contract: labels, comment controls, markers or template files.
      **Breaking for consuming repos?** <!-- yes / no, and why -->

## How it was tested

- [ ] `cd orchestrator && make test`
- [ ] `cd orchestrator && make lint`
- [ ] `node scripts/test-router.js` and `make conformance` (routing changes)
- [ ] Piloted on a scratch repo with `factory-test.yml`: <!-- link to the run, if any -->

## Checklist

- [ ] Both routers changed together, with a conformance fixture (routing changes)
- [ ] `FACTORY.md`, `docs/setup-guide.md` and `templates/` updated if behaviour changed
- [ ] No secrets, tokens, hostnames or personal data in code, fixtures or docs
