# Factory Pipeline States

Every issue in the factory carries exactly one `factory:*` label. That label is
the whole state — it decides which of the nine roles runs next, and nothing
advances without it moving.

The pipeline is not eleven equal steps. It is **three phases**, each ending at a
point where a person decides whether the machine keeps going. Between those
points the factory runs unattended.

## The pipeline

```mermaid
flowchart TB
  OPEN(["issue opened"]) --> A

  subgraph P1["PHASE 1 — DEFINITION"]
    direction LR
    A["factory:intake"] -- "Intake Analyst" --> B["factory:spec-ready"]
    B -- "G1 · Approved" --> C["factory:spec-approved"]
  end

  subgraph P2["PHASE 2 — DESIGN"]
    direction LR
    D["factory:planned"] -- "Architect<br/>auto-chained" --> E["factory:design-ready"]
    E -- "G2 · Approved" --> F["factory:design-approved"]
  end

  subgraph P3["PHASE 3 — DELIVERY"]
    direction LR
    G["factory:ready"] -- "Implementer" --> H["factory:in-review"]
    H -- "Reviewer" --> I["factory:in-test"]
    I -- "QA" --> J["factory:ready-to-ship"]
    J -- "G3 · merge" --> K["factory:deployed"]
  end

  C -- "Planner" --> D
  F -- "Dispatcher<br/>fans out" --> G
  A -. "blocker found" .-> X(["factory:blocked"])

  classDef state fill:#FFFFFF,stroke:#0B6E6B,stroke-width:1.5px,color:#0F1A1C
  classDef gate fill:#FAEDE4,stroke:#B24A17,stroke-width:2px,color:#4A2412
  classDef done fill:#DFEDEC,stroke:#0B6E6B,stroke-width:2.5px,color:#0A3B39
  classDef halt fill:#F5E6E3,stroke:#A33526,stroke-width:1.5px,color:#4E1811
  classDef entry fill:#EDF0F1,stroke:#9FADB1,stroke-width:1.5px,color:#3A464B

  class A,C,D,F,G,H,I state
  class B,E,J gate
  class K done
  class X halt
  class OPEN entry

  style P1 fill:#F4F6F6,stroke:#C6CFD2,color:#3A464B
  style P2 fill:#F4F6F6,stroke:#C6CFD2,color:#3A464B
  style P3 fill:#F4F6F6,stroke:#C6CFD2,color:#3A464B
```

Rust-filled states wait on a human. Everything else advances on its own the
moment the previous role finishes.

## The three gates

| Gate | State it holds at | The question | How it opens |
|---|---|---|---|
| **G1** | `factory:spec-ready` | Is the spec concrete enough to plan against? | Owner comments `Approved` |
| **G2** | `factory:design-ready` | Does the architecture actually solve it? | Owner comments `Approved` |
| **G3** | `factory:ready-to-ship` | May this land on `main`? | A human presses Merge |

G3 is not a comment. The factory has no permission to write to `main` at all —
it is enforced by the protected-branch hook, the `permissions.deny` block in
`.claude/settings.json`, and `factory-branch-guard.yml`, which opens a
`factory:incident` issue if a commit ever lands on `main` without a PR.

Who may approve at G1 and G2 is set per-gate in `.github/factory-approvers.json`.
Ship it with real usernames — the template's placeholder means "any collaborator
may approve," which is probably not what you want.

## State ledger

| State | Role that leaves it | Trigger that moves it |
|---|---|---|
| `factory:intake` | Intake Analyst | Applied automatically on `issues.opened` |
| `factory:spec-ready` | — waits — | Owner comments **Approved** · gate G1 |
| `factory:spec-approved` | Planner | Runs in the same workflow as the approval |
| `factory:planned` | Architect | Chained in-run — a factory-applied label emits no event |
| `factory:design-ready` | — waits — | Owner comments **Approved** · gate G2 |
| `factory:design-approved` | Dispatcher | Fans the epic out into task sub-issues |
| `factory:ready` | Implementer | Comment **Approved** on the task claims it |
| `factory:in-review` | Reviewer | Code review against the approved design |
| `factory:in-test` | QA | Test suite and acceptance criteria |
| `factory:ready-to-ship` | — waits — | Human merges the PR · gate G3 |
| `factory:deployed` | Release / Ops | Terminal for the epic |
| `factory:blocked` | — halted — | Any role may apply it; resume is manual |

The labels are mutually exclusive and are created by
`scripts/setup-labels.sh <owner> <repo>`. Re-running it patches existing labels
rather than duplicating them.

## Two things worth saying out loud

**Auto-chaining.** GitHub suppresses events for labels a workflow applied
itself — an anti-recursion measure. So `factory:planned` can never wake the
Architect, no matter how the trigger is written. The Architect is therefore
invoked *inside the Planner's own run*: one workflow, two roles. The same
constraint is why an implementer starts from a comment rather than from the
Dispatcher's label, and why a closing task has to re-run the Dispatcher
explicitly. See [[Control Architecture]].

**Re-dispatch.** The Dispatcher runs once, at `factory:design-approved`, which
strands any task that was blocked on a sibling. When a task sub-issue closes,
the factory re-runs the Dispatcher against its parent epic and releases whatever
was waiting. See [[Re-dispatch on Task Close]].

## See also

- [[Run Trace Issue 16]] — these states, walked end to end on a real epic
- [[Control Architecture]] — how an event picks a role
