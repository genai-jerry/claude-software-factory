# Design: Simulated System Tests

## Context

What exists, for Beacon, as of 17 Nov 2026:

- **The run.**
  - A beacon-api push to `staging` triggers beacon-infra `deploy-hostinger`, then `deploy-sim`, then
    `sim-scenarios`.
  - The run plays every `beacon/sim/scenarios/*.json` in a throwaway copy of the stack.
  - It posts the commit status `beacon/sim-scenarios` on the beacon-api commit, whose `target_url`
    is the Actions run.
  - It keeps `report.json` (each scenario's `name`, `result`, `failures`) in the artifact
    `sim-scenarios-report`.
- **The scenario format.**
  - `beacon/sim/scenario.py`, with data sets under `beacon/sim/scenarios/data/`.
  - Steps: `steer`, `start_ai_calls`, `settle`, `advance`, `whatsapp_reply`, `expect`.
  - Expectations check what the call, CRM, WhatsApp and mail simulators received, and any model
    request left without a canned answer.
  - Call scripts come from beacon-voice's call simulator. Today there are five: no answer,
    callback asked, booked, not interested, do not call me.
- **The pre-staging check.**
  - `tests/test_sim_controls.py` loads every shipped scenario into a workspace that is not
    Beacon's own, moves the clock into calling hours, and presses Start through the real gates.
  - It is parametrized over the pack directory, so a new scenario file is covered without
    writing a new test.
- **The factory.**
  - The Test Planner writes `system-tests/test-plan.md` and `test-data.md`, opens one
    `test(<epic>)` issue per case, and opens a loader task.
  - With `run_on: staging`, the Dispatcher releases cases at `factory:in-staging`.
  - A person's `Test Passed` or `Test Failed` sets `factory:test-passed` or `factory:test-failed`;
    `Test Failed` opens a fix task.
  - Verdicts are evidence at G3 and hold nothing.

## Goals / Non-Goals

**Goals:**
- An epic's cases that can be simulated run on the staging merge with no person involved.
- Their verdicts reach the epic, the test issues and Compass's G3 view.
- Gaps in the simulators are found at planning time, not on staging.

**Non-Goals:** see the proposal. In particular, no new gate and no automatic fix tasks.

## Decisions

### D1. The scenarios are a task, not a new role

The simulated-tests task is built by the Implementer, like the loader task: reviewed, QA'd,
assembled.
- Scenario files are code that must match what was actually built (data shapes, which outcome a
  call script yields).
- An Implementer working on the epic branch, with the code and the guide, is the role that can
  check them against it.
- CI's in-process Start test catches a scenario that cannot start.

*Alternative considered:* the Test Planner writes the scenarios at G2. Rejected, because the code
does not exist yet: the scenarios would be guesses, and fixing them would need a second pass anyway.

### D2. The repository's guide decides what can be simulated

The Test Planner reads `simulate.guide`, a document in the consuming repository. It holds:
- the format;
- the call scripts and simulator controls that exist;
- a list of what cannot be simulated, with the reason to quote: real audio, carrier behaviour,
  a real phone's call screening, judging a screen.

The factory's prompt stays generic, and each repository owns its truth. For Beacon, the guide also
records what its fixes established: scenario workspaces get a line, agent, schedule, API key, CRM
install and gateway number from the loader; the runner starts at 10:00 UTC; clock stops wait for
call reports.

### D3. Gap tasks go to the simulator's repository

`simulate.simulators` maps what is simulated to a repository, for example
`{"calls": "genai-jerry/beacon-voice", "crm": "genai-jerry/beacon-connectors",
"whatsapp": "genai-jerry/beacon-whatsapp"}`. A case that needs a missing call script gets one gap
task in the `calls` repository, as an ordinary cross-repository task under the epic, the same way
the Planner already opens tasks in other repositories.

A gap task is merged to that repository's `staging` with the epic. A change in a simulator
repository only reaches the simulator through a staging deploy. Beacon's beacon-voice, beacon-whatsapp
and beacon-connectors trigger deploys only from `main`, so the Release Manager's existing
integration step must dispatch that service's staging deploy, as it already must for any task in
those repositories.

### D4. Reading results: a status event when there is one, a sweep in any case

- The orchestrator handles a `status` event whose `context` equals `simulate.status_context` and
  whose state is final. This needs the App to be subscribed to statuses.
- The existing reconcile loop also checks, every 10 minutes, the integration branch head's status
  for every repository with an epic at `factory:in-staging`. So results arrive even without the
  subscription, at most 10 minutes late.

To read a result:
1. Take the run id from the status's `target_url`.
2. List the run's artifacts in `simulate.run_repo`, download `sim-scenarios-report`, and read
   `report.json`.
3. For each in-staging epic whose integration merge is an ancestor of the status's commit (compare
   API), match scenarios by `covers`.

The run id is stored per epic in the ledger, so a run is recorded once.

*Why not have the workflow call the factory?* beacon-infra would then need the factory's address
and a token. The status already exists and names the run.

### D5. Matching scenarios to cases by `covers`, and the report carrying it

Each scenario file holds `"covers": ["genai-jerry/beacon-api#667 ST-21"]`, and the runner copies
`covers` into each result in `report.json` (a small beacon-api change). A scenario's file name is
not used for matching, so one scenario may cover two cases and a renamed file breaks nothing.

### D6. Verdict handling

| Report result | Case label | Comment |
|---|---|---|
| `pass` | `factory:test-passed` | "Simulated: passed in run <link> on <sha>." |
| `fail` / `error` | `factory:test-failed` | the failing steps from `failures`, verbatim |

- A person's later verdict wins until a newer run (D4) records one.
- A case at `factory:test-failed` with a fix in flight is left alone until the fix lands. The next
  run then records it.
- No fix task is opened by a run (interpretation 3).

### D7. The epic's summary

There is one comment per recorded run, kept short:
- the simulated counts;
- the manual cases still open, by number and title;
- each failing simulated case and its step;
- each failing scenario that covers none of this epic's cases, as a regression with its owner
  epic when its `covers` names one;
- the run's link.

Compass reads the same data from the labels and comments (D8). Nothing new is stored for it.

### D8. Compass

- The Test board already lists cases by label. It adds a chip, *Simulated* or *Manual (reason)*,
  read from the case body's `Execution:` line, and for a simulated verdict the run link from the
  factory's comment marker `<!-- sim-run: <run id> <sha> -->`.
- The production decision for an epic shows the counts and failing cases from the same source, and
  the regressions from the epic summary's marker.

### D8a. From a failure to a fix, optionally expedited

`Test Failed, expedite` is handled by the existing `Test Failed` branch:
1. It files the fix the same way.
2. It then checks the sender against the `expedite` approvers.
3. If they are one, it applies `factory:expedite` to the new fix task alone.

`is_expedited` already honours the marker on the task itself, so the auto-advance map runs that
task through implementation, review, QA and assembly, and stops at GS as always. Compass's two
buttons post the two comments as the signed-in person, through the existing comment route. Only a
signed-in person can trigger it, and the router checks their access as it does for every comment.

### D9. `Simulate tests` adoption

A new exact-match comment on an epic, from a staging approver, handled like `Plan tests`. It runs
the Test Planner in its revision mode with the instruction to sort the cases, open the task and the
gap tasks, and leave the case numbers unchanged.

## Risks / Trade-offs

- **The guide and the simulators drift.** A guide that promises a call script the simulator lacks
  produces a scenario that fails on staging. *Mitigation:* the in-process Start test in CI, and the
  guide lists scripts by the call simulator's own names, so a reviewer can check them.
- **Long packs.** Every epic adds scenarios, and clock scenarios run one at a time: 7 take about
  3 minutes on the server, so about 37 would take about 15. *Mitigation:* acceptable for now. The
  runner can later split by epic.
- **A staging run that carries two epics** records for both. The summary of each names the
  other's failures only as regressions.
- **A scenario that is flaky** flips a case between runs. The comment always names both runs, so a
  flip is visible. The settle-for-call-reports fix (beacon-api#736) removed the one known race.

## Migration Plan

1. beacon-api:
   - add the `simulate` block and `docs/beacon/sim-scenarios.md`;
   - make the runner copy `covers` into `report.json`.
2. claude-software-factory: the Test Planner changes, `Simulate tests`, the status handler and the
   sweep, FACTORY.md §4b.
3. Compass: the Test board chips and the G3 counts.
4. Comment `Simulate tests` on beacon-api#667, then build the task and gap tasks through the normal
   pipeline. Gate GS is then opened by a person as usual.
5. Rollback: remove the `simulate` block. Everything then behaves as today, and the scenario files
   stay as regression checks.

## Open Questions

Settled with the owner on 17 Nov 2026:
1. A simulated failure opens no fix task by itself. It is shown clearly, with a one-action
   **Create fix task**, and **Create fix task (expedite)** expedites that one fix (D8a).
2. GS waits for the simulated-tests task as for any task of the epic.
