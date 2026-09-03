# Conformance fixture schema

One fixture = one routing decision: a GitHub event arriving at a repo in a
known state, and the route + side effects every conforming engine must
produce for it. The fixtures in `fixtures/*.json` are the **canonical
routing decision table** — the workflow's JS router (`scripts/test-router.js
--fixtures`) and the orchestrator's Python router
(`orchestrator/tests/test_conformance.py`) both run every fixture in CI, and
a change to routing behaviour lands as a fixture change plus both
implementations, in one PR.

Fixtures are declarative and engine-neutral: they describe GitHub state and
GitHub effects, never workflow steps or graph nodes. Machine-validated by
`fixture.schema.json` (JSON Schema draft 2020-12).

## Top-level shape

```json
{
  "name": "gating-off-issue-opened",
  "description": "gating OFF - a filed issue goes straight to intake",
  "config": { ... },
  "repo": { "issues": [ ... ] },
  "event": { ... },
  "expect": { ... }
}
```

A file contains a single fixture object. File name = `<name>.json`.

## `config` — the consuming repo's factory config files

Each key is optional; an absent key means "file absent", which must route
exactly like today's defaults.

| Key | Models file |
|---|---|
| `release` | `.github/factory-release.json` |
| `approvers` | `.github/factory-approvers.json` |
| `orchestrator` | `.github/factory-orchestrator.json` |
| `testing` | `.github/factory-testing.json` (system tests, §4b) |

Values are the parsed JSON contents, verbatim. The string value
`"invalid-json"` means the file exists but does not parse (engines must
treat it as absent — the router's `loadJson` swallows parse errors).

## `repo.issues[]` — pre-existing issues

```json
{
  "number": 5,
  "title": "Add renewals",
  "labels": ["factory:intake"],
  "authorType": "User",            // "User" | "Bot" (default "User")
  "state": "open",                 // "open" | "closed" (default "open")
  "isPullRequest": false,          // true = this "issue" is a PR (comment routing skips it)
  "milestone": 7,                  // milestone number, or null/absent
  "comments": [ { "body": "..." } ]
}
```

`repo.milestones[]` (optional) names milestones referenced by number:

```json
{ "number": 7, "title": "v0.4", "htmlUrl": "u" }
```

## `event` — what arrived

Exactly one of these shapes, selected by `event.name`:

- `issues`: `{ "name": "issues", "action": "opened|labeled|closed|milestoned|demilestoned", "issue": 5, "label": "factory:fast-track", "milestone": 7, "sender": "boss" }`
  (`label` only for `labeled`; `milestone` only for `milestoned`/`demilestoned`;
  `issue` is the number of an entry in `repo.issues`)
- `issue_comment`: `{ "name": "issue_comment", "action": "created", "issue": 5, "comment": { "body": "Approved", "login": "boss", "authorAssociation": "OWNER", "authorType": "User" } }`
- `milestone`: `{ "name": "milestone", "action": "created", "milestone": 7 }`
- `push`: `{ "name": "push", "ref": "refs/heads/main", "defaultBranch": "main" }`
- `workflow_dispatch`: `{ "name": "workflow_dispatch", "role": "reviewer", "issue": "12" }`

## `expect` — the decision and its visible effects

All keys optional; assert only what the fixture is about. Unlisted effects
are not constrained (harnesses check what is written, nothing more).

```json
{
  "role": "intake",                  // routed role, or "none"
  "issues": ["5"],                   // JSON array of issue numbers the role targets
  "releaseIssue": "1",               // tracker number when a release may complete ("" = none)
  "labels": {
    "5": { "has": ["factory:backlog"], "not": ["factory:intake"] }
  },
  "comments": {
    "5": { "countAtLeast": 1, "contains": ["Plan release"], "notContains": ["..."] , "count": 1 }
  },
  "createdIssues": [
    { "titlePattern": "^release\\(7\\):", "labels": ["factory:release", "factory:release-planning"], "bodyContains": ["Nothing is running yet", "@boss"] }
  ],
  "createdCount": 1                  // exact number of issues the router filed
}
```

Semantics:

- `labels.<n>.has` / `.not` — final label state on issue `n` after routing.
- `comments.<n>` — comments on issue `n` **posted by this routing pass**
  (harnesses count relative to the fixture's pre-existing `comments`).
  `contains` matches substrings anywhere in any new comment.
- `createdIssues` — issues the router itself filed (trackers, the profile
  issue), matched in order of creation.
- `role`/`issues`/`releaseIssue` — the routing outputs. For the Actions
  engine these are the `route` job outputs; for the orchestrator they are
  the router's decision object. Their meaning is identical.

## Two-pass fixtures

`repeatEvent: true` (top level, optional) runs the same event a second time
against the mutated world and applies `expectSecond` (same shape as
`expect`) to the second pass. This is how "notices are said once" and
"redelivery is idempotent" are pinned.

## Release-chain fixtures

`chain: "release"` (top level, optional) runs the release fan-out step
after routing, with the tracker from `expect.releaseIssue`. Its effects
fold into the same `expect` block (e.g. released issues now `has:
factory:intake`); `expect.chainIssues` / `expect.chainCount` assert the
fan-out's own outputs.

## Claim fixtures are engine-sided

A fixture whose `config` carries an `orchestrator` key pins the **Actions
engine's** claim behaviour (stand down when an external engine is named).
The Python conformance harness skips those — the claim protocol is
engine-specific by design — and `orchestrator/tests/test_claim.py` covers
this engine's half against the same configurations, asserting that for
every declared engine value exactly one engine acts.

## What fixtures deliberately do not encode

- `factory:in-progress` application/removal, snapshots, and the no-op guard
  — run-lifecycle guards, specified in `orchestration/engine-contract` and
  tested per engine, not per routing decision. The marker as *pre-existing
  repo state* is fair game and is pinned here, because engines must agree on
  what it means for a route: it does not block the fast lane
  (`labeled-fast-track-ignores-marker`) and it does decline a second
  implementation start (`approved-ready-task-run-live`).
- Model resolution, prompt assembly, workspace isolation — execution
  concerns with their own tests.
- The `<!-- factory-agent -->` marker on router-posted comments IS asserted
  (via `contains`), because it is part of the visible trace contract.
