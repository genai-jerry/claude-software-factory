# Simulated System Tests (an epic's cases run in the simulated environment)

## Why

A repository can now have a **simulated environment**: all of the product, with every outside
system replaced by a simulator and a shared clock a test can move forward. Beacon has one
(genai-jerry/beacon-api epics #553 and #610). Every merge to `staging` redeploys it and runs
every scenario file in `beacon/sim/scenarios/` in a throwaway copy, then posts the result on the
merged commit as the status `beacon/sim-scenarios`. As of 17 Nov 2026, the hand-written regression
pack passes 7 of 7 there.

The factory does not use it. An epic's system test cases (FACTORY.md §4b) are still written only for
a person, with a real handset on staging. Epic beacon-api#667 has 39 of them. Most of what they
check is call outcomes, stop rules, a schedule over ten days, a cap and callbacks. A person cannot
wait ten days, but the simulator can. And nothing that the simulator's run finds reaches the epic,
its test issues or the person deciding at gate G3.

So the cases that can run in the simulator should run there, automatically, on the staging merge
that puts the epic on staging. Their results should reach the person who decides whether the epic
goes to production. Cases that need a person (real audio, a real phone, a screen) stay manual, as
today.

## What Changes

- **The Test Planner sorts each case.** In a repository whose `.github/factory-testing.json` has a
  `simulate` block, each case's `Execution:` is `simulated`, or `manual` with the reason it cannot
  be simulated (real audio, a carrier, a person's judgement of a screen). The rules are in the
  repository's own simulation guide, which the block names.
- **One simulated-tests task per epic**, opened by the Test Planner beside the test-data loader
  task. Like the loader task, it is cap-exempt and ordinary from then on: built, reviewed and QA'd,
  and assembled on the epic branch.
  - Its work: one scenario file for each simulated case (`<pack>/<epic>-st-<n>.json`), with the
    data sets it needs. Each file names the case it covers (`covers`).
  - The repository's own tests check every scenario's format and press Start in-process through
    the real product gates. For Beacon that is `tests/test_sim_controls.py`, which covers every
    file in the pack. So a scenario that cannot even start fails in CI, before staging.
- **Simulator gaps become tasks.** A case may need something no simulator does yet (a call that
  goes to voicemail, a number that does not exist). The Test Planner then opens a task in the
  simulator's repository (for Beacon, beacon-voice's call scripts), and the simulated-tests task
  is blocked by it.
- **Results come back by themselves.** When the simulator's run finishes for a staging commit that
  carries the epic, the factory reads the run's report:
  - each simulated case goes to `factory:test-passed` or `factory:test-failed`, with a comment
    naming the run, the commit and, for a failure, the failing step in the runner's own words;
  - the epic gets one summary comment, which also names any regression scenario that failed.
  - A simulated failure opens no fix task by itself. It is shown clearly (the case, the failing
    step in the runner's words, the run), and the person turns it into a fix task with one action:
    **Create fix task** (the same as commenting `Test Failed`), or **Create fix task (expedite)**
    (comment `Test Failed, expedite`), which marks that one fix task `factory:expedite` so it builds
    itself up to gate GS.
- **Compass shows them at gate G3.** The Test board and the production decision show each case as
  simulated or manual, its verdict and a link to the run. A failed case has the two buttons.
- **Adoption for an epic already past G2:** a staging approver comments `Simulate tests` on the
  epic. The Test Planner then re-sorts the existing cases, keeping their identifiers, and opens the
  task. #667 is the first.

## Capabilities

### New Capabilities

- `system-tests/simulated-cases`: how cases are sorted, the simulated-tests task, simulator gap
  tasks, how results are read back and recorded, and the adoption comment.

### Modified Capabilities

- None as delta specs: this repository's `openspec/specs/` holds no capability yet. The
  `add-system-test-generation` change, which defines the Test Planner and test cases, is unarchived.
  This change adds a capability beside it and names the points it extends.

## Impact

- **claude-software-factory:**
  - `commands/testplanner.md`: sorting cases, the task, gap tasks, `Simulate tests`.
  - Orchestrator: read the sim-scenarios result and record verdicts.
  - `templates/factory-testing.json`: the `simulate` block.
  - FACTORY.md §4b.
  - Labels unchanged: the existing `factory:test-passed` and `factory:test-failed` are used.
  - The router: `Test Failed, expedite` on a case.
- **software-factory-view (Compass):** the Test board and G3 decision show simulated verdicts and
  the run link.
- **beacon-api:**
  - `.github/factory-testing.json` gains its `simulate` block.
  - A simulation guide (`docs/beacon/sim-scenarios.md`): format, call scripts, what cannot be
    simulated.
  - The runner copies each scenario's `covers` into `report.json`.
- **beacon-voice:** new call scripts when an epic's gap tasks ask for them (#667's first).
- **beacon-infra:** none. The run and its report artifact already exist.

## Non-goals

- Simulating real audio, carrier behaviour, call screening on a real phone, or judging how a screen
  looks. Those stay manual.
- Gating GS or G3 on simulated results. With `run_on: staging` nothing holds GS today, and the
  verdicts are evidence at G3, as manual verdicts are.
- Opening fix tasks automatically on a simulated failure. One action from the person does it.
- Repositories without a simulated environment: without a `simulate` block nothing changes.
- A simulator for a platform the stack does not have (for example Gnani).

## Interpretations taken

1. "Simulated in the simulation environment" means the throwaway copies that run after each
   staging deploy, not the standing simulator testers use.
2. A case is simulated only when every expected result in it can be checked from what the
   simulators received or the product's API answers. If any one needs a person, the whole case is
   manual. It is not split into two cases.
3. The person decides at G3, so a simulated failure informs that decision and does not block it.
4. The epic's scenario files stay in the pack after the epic ships, so they keep running as
   regression checks on every later staging merge.
5. Results are recorded only for an epic that is `factory:in-staging`, from a run on a staging
   commit that contains the epic's integration merge.
