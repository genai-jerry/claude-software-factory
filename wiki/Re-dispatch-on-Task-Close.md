# Re-dispatch on Task Close

The Dispatcher runs once, at design approval. Anything that depended on a
sibling task was left unlabelled — invisible to the factory and to the people
working it. This page is the fix, and it cost **one word in a trigger list**.

## The dependency shape

```mermaid
flowchart LR
  EPIC["epic 16<br/>factory:design-approved"]

  subgraph FREE["RELEASED AT DISPATCH"]
    T17["task 17<br/>factory:ready"]
    T18["task 18<br/>factory:ready"]
    T19["task 19<br/>factory:ready"]
    T20["task 20<br/>factory:ready"]
  end

  subgraph HELD["HELD BACK — no label at all"]
    T21["task 21"]
    T22["task 22"]
    T23["task 23"]
  end

  EPIC --> FREE
  EPIC --> HELD
  T20 -- "blocks" --> T21
  T20 -- "blocks" --> T22
  T20 -- "blocks" --> T23

  classDef epic fill:#DFEDEC,stroke:#0B6E6B,stroke-width:2.5px,color:#0A3B39
  classDef ok fill:#FFFFFF,stroke:#0B6E6B,stroke-width:1.5px,color:#0F1A1C
  classDef block fill:#FAEDE4,stroke:#B24A17,stroke-width:2px,color:#4A2412
  classDef held fill:#F5E6E3,stroke:#A33526,stroke-width:1.5px,color:#4E1811,stroke-dasharray:4 3

  class EPIC epic
  class T17,T18,T19 ok
  class T20 block
  class T21,T22,T23 held

  style FREE fill:#F4F6F6,stroke:#C6CFD2,color:#3A464B
  style HELD fill:#FBF3F1,stroke:#D9BDB6,color:#5A3A33
```

An unlabelled sub-issue is not "waiting" as far as the factory is concerned — it
does not exist in *any* state, so no trigger can ever pick it up.

## Before and after

| | Before | After |
|---|---|---|
| | Task 20 merges and the epic stalls | Task 20 merges and the next wave starts |
| | Tasks 21–23 still carry no `factory:*` label | `issues.closed` reaches the pipeline |
| | Nothing is watching for task completions | Router finds the parent epic and checks its state |
| | The epic sits at `factory:design-approved` looking finished | Dispatcher re-runs against epic 16 |
| | Only a manual `workflow_dispatch` of the Dispatcher unsticks it | Tasks 21–23 get `factory:ready` within the minute |

## The re-dispatch path

```mermaid
flowchart TB
  A(["task 20 PR merged · sub-issue closes"]) --> B["issues.closed reaches the caller stub"]
  B --> C{"does the task have<br/>a parent epic?"}
  C -- no --> Z1["no route"]
  C -- yes --> D{"epic still at<br/>design-approved?"}
  D -- no --> Z2["no route<br/>epic is past fan-out"]
  D -- yes --> E["role = dispatch<br/>targeted at the epic"]
  E --> F["read every child of the epic"]
  F --> G{"child already carries<br/>a factory:* label?"}
  G -- yes --> H["skip · a worker owns it"]
  G -- no --> I["apply factory:ready"]
  H --> J["post summary on the epic"]
  I --> J
  J --> K(["21, 22, 23 are claimable"])

  classDef ev fill:#EDF0F1,stroke:#9FADB1,stroke-width:1.2px,color:#3A464B
  classDef core fill:#FFFFFF,stroke:#0B6E6B,stroke-width:1.5px,color:#0F1A1C
  classDef dec fill:#DFEDEC,stroke:#0B6E6B,stroke-width:2px,color:#0A3B39
  classDef stop fill:#F5E6E3,stroke:#A33526,stroke-width:1.5px,color:#4E1811
  classDef good fill:#DFEDEC,stroke:#0B6E6B,stroke-width:2.5px,color:#0A3B39

  class A,B ev
  class E,F,H,I,J core
  class C,D,G dec
  class Z1,Z2 stop
  class K good
```

## The two guards

**The epic must still be at `factory:design-approved`.** If it has already
advanced — every task labelled, work underway, or the epic itself past fan-out —
a late task closing must not drag the Dispatcher back through a stage it has
finished. Any other epic state means no route.

**A child that already carries a label is never relabelled.** If task 22 is
sitting at `factory:in-review` because someone claimed it, re-dispatch skips it
entirely. Only children with no `factory:*` label at all are candidates. This is
what makes the step safe to run repeatedly: it is idempotent, and it never takes
work out from under whoever owns it.

## The change

The router already knew how to handle a closing task. What it never received was
the event — the caller stubs only subscribed to `opened` and `labeled`.

```diff
  on:
    issues:
-     types: [opened, labeled]
+     types: [opened, labeled, closed]
    issue_comment:
      types: [created]
```

**Where it landed.** The same line changed in
`templates/workflows/factory-pipeline.yml` in the factory repo, so every future
install gets it, and in the consuming repo's own stub, so that repo gets it now.

**Why the stub and not the reusable workflow.** A called workflow cannot declare
its own triggers. Events are the one thing a consuming repo genuinely owns —
which is also why the stub is the only file that ever needs touching to upgrade.

**Scope.** Dispatcher logic is unchanged. It is the same code path that ran at
design approval, invoked a second time with the epic as its target.

## Upgrading an existing install

If a repo was set up before this change, its stub still has the two-event list.
Fix it in place:

1. Edit `.github/workflows/factory-pipeline.yml` in the consuming repo.
2. Add `closed` to `issues.types`.
3. Merge to the **default branch** — GitHub only fires workflow files that
   physically exist there.

Until that lands, epics still work; their blocked tasks just need a manual
`workflow_dispatch` of the `dispatch` role against the epic to be released.

## See also

- [[Run Trace Issue 16]] — step 05 is this mechanism firing for real
- [[Control Architecture]] — the router branch that routes `issues.closed`
