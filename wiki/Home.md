# Software Factory

An agent-driven delivery pipeline for Claude Code. A plain GitHub issue goes in;
a specced, planned, designed, implemented, reviewed, tested and released change
comes out — with human approval gates and no ability for an agent to put
anything on `main`.

These pages are the **visual companion** to the handbook. They describe the same
system [`FACTORY.md`](https://github.com/genai-jerry/claude-software-factory/blob/v1/FACTORY.md)
specifies; where the two disagree, `FACTORY.md` wins.

## The five sheets

| | Page | What it answers |
|---|---|---|
| 01 | [[Factory Pipeline States]] | What are the states, and what moves work between them? |
| 02 | [[Run Trace Issue 16]] | What does one epic actually look like, start to finish? |
| 03 | [[Control Architecture]] | How does a GitHub event become a running role? |
| 04 | [[Re-dispatch on Task Close]] | How do tasks blocked behind a sibling get released? |
| 05 | [[Release Gating]] | How do you stop every filed issue from starting an agent? |

## The shape of it in one paragraph

GitHub is the state machine: milestones are releases, and issues, sub-issues and
`factory:*` labels encode *where* work is — a label change is what wakes an
agent. OpenSpec is the content: *what* is being built lives in
`openspec/changes/<issue>-<slug>/`. Issues carry state plus a link, never spec
content — that is the rule that stops the two sources of truth from drifting.
Ten roles move work between the states, and the gates stop the machine to ask a
person.

## Where the logic lives

A consuming repo holds seven files and **none of them are logic**:

```
.factory/profile.json                       # the only genuinely-yours file
.github/workflows/factory-pipeline.yml      # caller stub — triggers + version pin
.github/workflows/factory-branch-guard.yml
.github/factory-models.json
.github/factory-approvers.json
.github/factory-release.json                # optional — release gating
.claude/settings.json
```

The pipeline body, the eleven role prompts and the protected-branch hook all stay
in `claude-software-factory` and are pulled in at run time. Upgrading is a
version bump in the stub.

## Related

- [`FACTORY.md`](https://github.com/genai-jerry/claude-software-factory/blob/v1/FACTORY.md) — the handbook, and the authority
- [`docs/setup-guide.md`](https://github.com/genai-jerry/claude-software-factory/blob/v1/docs/setup-guide.md) — installing the factory in a repo, step by step
- [`docs/case-study/`](https://github.com/genai-jerry/claude-software-factory/tree/v1/docs/case-study) — how the factory was built and what it cost
