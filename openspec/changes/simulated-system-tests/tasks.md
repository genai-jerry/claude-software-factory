# Tasks: Simulated System Tests

Repositories: claude-software-factory (this change), software-factory-view (Compass), beacon-api.
Build in this order.

## 1. beacon-api: what the factory reads

- [x] 1.1 Add the `simulate` block to `.github/factory-testing.json`:
      - `pack`: `beacon/sim/scenarios`;
      - `guide`: `docs/beacon/sim-scenarios.md`;
      - `status_context`: `beacon/sim-scenarios`;
      - `run_repo`: `genai-jerry/beacon-infra`;
      - `simulators`: calls → beacon-voice, crm → beacon-connectors, whatsapp → beacon-whatsapp.
- [x] 1.2 Write `docs/beacon/sim-scenarios.md`:
      - the scenario format with one worked example;
      - the call scripts the call simulator has, by name;
      - what a load gives a workspace;
      - the runner's 10:00 UTC start;
      - the list of what cannot be simulated, with the reason to quote.
- [x] 1.3 Runner: copy each scenario's `covers` into its `report.json` result. Allow a `covers`
      field in `beacon/sim/scenario.py`'s format check. Add tests for both.
- [x] 1.4 Verify: a pack file with `covers` loads, runs, and its report row carries `covers`.

## 2. claude-software-factory: the Test Planner

- [x] 2.1 `templates/factory-testing.json`: document the `simulate` block in `_comment`. The config
      loader reads it and exposes it to the roles and the router. Add tests that it parses and is
      absent by default.
- [x] 2.2 `commands/testplanner.md`, with a `simulate` block:
      - sort each case, quoting the guide for a manual one;
      - open the simulated-tests task (step 4b, beside the loader task);
      - open gap tasks in the simulator repositories;
      - on a revision, update rather than duplicate.
- [x] 2.3 Router: handle `Simulate tests` on an epic from a staging approver. It runs the Test
      Planner in revision mode and replies when there is no `simulate` block. Add conformance
      fixtures for both cases.
- [x] 2.4 Router: handle `Test Failed, expedite` per D8a. It files the fix as `Test Failed` does and
      adds `factory:expedite` to the fix task when the sender is an expedite approver; otherwise it
      says why not. Add tests for both cases and for the case already having a fix.
- [x] 2.5 FACTORY.md §4b: simulated cases, the task, gap tasks, how results are recorded, the
      `Simulate tests` and `Test Failed, expedite` comments. Update §2a with the trigger rows.

## 3. claude-software-factory: reading results

- [x] 3.1 Handle the `status` event: match `context` to a repository's `simulate.status_context`,
      final states only.
- [x] 3.2 Add the reconcile sweep: every 10 minutes, for each repository with an epic at
      `factory:in-staging`, read the integration branch head's status.
- [x] 3.3 Read the result:
      - take the run id from `target_url`;
      - download `sim-scenarios-report` from `run_repo`;
      - parse `report.json`;
      - keep only epics whose integration merge is an ancestor of the commit.
- [x] 3.4 Record verdicts per D6: labels and comments with the `<!-- sim-run: … -->` marker, skip a
      case with a fix in flight, a person's later verdict stands until a newer run, once per run per
      epic (ledger).
- [x] 3.5 Post the epic summary per D7, regressions included.
- [x] 3.6 Tests: pass, fail, error, a repeat run, a run on a commit without the epic, a regression,
      a person's verdict in between, a failed artifact download (nothing recorded, retried by the
      sweep).

## 4. software-factory-view (Compass)

- [ ] 4.1 Test board: the Simulated / Manual chip with its reason, and the run link on a simulated
      verdict.
- [ ] 4.2 Production decision: simulated passed and failed counts, manual cases still open,
      failing cases with their step, regressions, the run link.
- [ ] 4.2a On a failed case: **Create fix task** and **Create fix task (expedite)**, which post
      `Test Failed` / `Test Failed, expedite` as the signed-in person. Show the fix instead once one
      exists.
- [ ] 4.3 Tests for both views.

## 5. First use: beacon-api#667

- [ ] 5.1 Comment `Simulate tests` on #667. Check the sorting: about ST-4..ST-33 simulated; ST-1..3
      and ST-34..39 manual, with reasons.
- [ ] 5.2 The gap tasks are expected in beacon-voice: call scripts for voicemail, switched off,
      number does not exist, wrong number, a short call with no audio, someone else answering, and
      a cut-off conversation. They are built and deployed to the simulator.
- [ ] 5.3 The simulated-tests task is built, reviewed, QA'd and assembled. Gate GS is then opened by
      a person.
- [ ] 5.4 After the staging merge, confirm each simulated case has a verdict, the epic has a
      summary, and Compass shows both.
