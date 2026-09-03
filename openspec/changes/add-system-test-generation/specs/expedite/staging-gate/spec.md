# Delta Spec: expedite/staging-gate (system tests)

## MODIFIED Requirements

### Requirement: The epic-ready state

(Modifies `expedite/staging-gate`.) A state label `factory:epic-ready` SHALL
mean: the epic's implementation is complete and proven as far as it can be
without touching staging — with `epics: true`, every task is
`factory:on-epic`, the epic branch's full suite is green, **and, when
`.github/factory-testing.json` sets `system_tests: true` with `mode: gate`,
every open `test(<epic>)` sub-issue is `factory:test-passed`**; with
`epics: false`, every task is `factory:ready-to-ship`. It SHALL be set on the
epic by the factory: by the Release run that lands the last task in its end
state, or by the Dispatcher when a re-dispatch — on task close, chained after
a landing, or routed by the last `Test Passed` — finds every child already
there. It SHALL be created by `scripts/setup-labels.sh`, sit between
`factory:on-epic` and `factory:in-staging` in the state table, and apply to
expedited and non-expedited epics alike.

#### Scenario: Last assembled task flips the epic

- **WHEN** a Release phase-1 run moves the final task of an epic to
  `factory:on-epic`, the epic branch suite is green, and system tests are off
  or every test sub-issue is already `factory:test-passed`
- **THEN** the epic flips to `factory:epic-ready` and no epic → integration
  merge happens in that run

#### Scenario: Set for non-expedited epics too

- **WHEN** a human manually started every stage of an epic and its last task
  reaches `factory:on-epic`
- **THEN** the epic still flips to `factory:epic-ready` — the informal
  "start Release phase 2 by hand" step no longer exists

#### Scenario: Last test flips the epic

- **WHEN** every task is `factory:on-epic` under `mode: gate` and the last
  open test sub-issue flips to `factory:test-passed`
- **THEN** the Dispatcher routed by that comment flips the epic to
  `factory:epic-ready`
