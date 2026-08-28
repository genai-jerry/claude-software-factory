# Execution architecture: from tempdir-in-the-API to managed workers and workspaces

Status: plan. Stage 1 (webhook intake decoupled from processing) is shipped.
This document reviews what the orchestrator actually does today and specifies
Stages 2–5.

## Target

```
webhook ──► graph routes, enqueues a job, returns
                  │
                  ▼
            ┌──────────────────┐    events[] ──► Console run log
            │ WorkspaceManager │    (append-only notifications)
            │ key: repo#issue  │
            └────────┬─────────┘
                     │ lease
                     ▼
            Worker process (claude + observer)
                     │
                     ▼
            idle workspace ──► reused on next role
                     │
                     ▼
            PR merged | TTL | disk cap  ──► delete
```

Three things must become independently manageable: **orchestration** (the
graph), **execution** (the worker process), and **processing space** (the
workspace). Today all three are one Python process and one `mkdtemp`.

---

## 1. What the system does today

### 1.1 Intake is already asynchronous; execution is not

`webhook.py` is honest about the contract: verify HMAC → `record_delivery`
→ 202. A single asyncio task (`worker_loop`) then claims pending rows and
calls `await asyncio.to_thread(processor, event, payload)`.

That is where "async" stops. `Processor.__call__` (`graph.py`) calls
`self.graph.invoke(state, config)` **synchronously**. `run_role_node` calls
`execute_role` inline, which calls `RoleRunner.run`, which `subprocess.Popen`s
`claude -p` and blocks up to `ROLE_TIMEOUT_SECONDS` (default 2700s). So a
45-minute role occupies a thread of the API process for 45 minutes, and every
ledger write, every phase note, the observer, `commands.test`, `git push` and
`gh pr create` all live inside that process.

Consequence: **killing the API kills the run.** `_run_bounded` passes
`start_new_session=True`, so the `claude` child does survive a SIGTERM aimed at
the API's process group — but nobody is left to read its stdout, run the tests,
push the branch, clear `factory:in-progress`, or write `finish_run`. A surviving
child is an orphan, not a continuing run. On restart, `requeue_processing()`
flips the delivery back to `pending` and the whole role is re-executed from a
fresh clone.

### 1.2 The workspace is an anonymous tempdir

`RoleRunner.run`:

```python
workspace = Path(tempfile.mkdtemp(prefix=f"run-{role}-{issue}-", dir=self.workspace_root))
try:
    ...
finally:
    shutil.rmtree(workspace, ignore_errors=True)
```

Properties worth naming:

- No record. Nothing outside the stack frame knows the directory exists. A
  crashed process leaks it silently; nothing ever reaps it.
- Full clone per role. Every reviewer/QA/fasttrack run on the same issue
  re-clones the repo.
- `HOME=str(workspace)` — Claude's own state (`~/.claude`) is written inside
  the tree that is about to be deleted. This is the asset Stage 5 wants.
- The clone URL is `https://x-access-token:<token>@github.com/...`, so the
  installation token is persisted in `.git/config` for the life of the
  directory.

### 1.3 Concurrency control is per-process and partly dead

`RoleRunner._slots = threading.Semaphore(max_parallel or cfg.max_parallel_default)`
bounds concurrent roles **inside one process**. `Engine.max_parallel(port)`
reads `runners.max_parallel` from the repo's `factory-orchestrator.json` — and
is never called by anything. The repo-level cap is currently inert; the only
live cap is the global `MAX_PARALLEL` env default of 4.

### 1.4 Observability is a file pair plus a DB row

`LiveRunLog` writes `TRANSCRIPT_DIR/<run_id>.log` (raw stdout, appended as it
streams) and `<run_id>.events.jsonl` (one JSON notification per line). The
`runs` table holds outcome, model, `guards` JSON (whose `phase` is the "Now"
field), and `transcript_path`. `GET /runs/{id}` merges the events in;
`GET /runs/{id}/transcript` serves the log.

The Console proxies these same-origin (`apps/api/src/routes/orchestrator.ts`)
and renders them at `/runs/:runId` and inline on the epic workspace, polling
every 2–3s until `finished_at` is set.

There is **no view of the machine**: no queue depth, no list of live
processes, no pids, no workspaces, no disk. The Console can answer "how is run
X going" and cannot answer "what is this box doing right now".

### 1.5 What is genuinely good and must not regress

- The delivery ledger is already a restart-safe queue with idempotency.
- The graph's `chain_node` gates architect on the planner *actually* reaching
  `factory:planned` by re-reading GitHub. Chaining correctness does not depend
  on in-process state.
- Every node re-reads GitHub before acting; checkpoint state is bookkeeping.
- Guards (in-progress marker, no-op detection, failure report) are centralised
  in `execute_role`'s try/finally.

Stages 2–4 must preserve all five.

---

## 2. Stage 2 — Worker process (async execution)

**Goal:** another OS process does the work. The graph still *joins* — planner
must finish and apply `factory:planned` before architect runs — but it joins on
a durable completion record, not on a call stack.

### 2.1 Job queue in the ledger

New table, alongside `webhook_deliveries` and `runs`:

```
jobs
  id              TEXT PK
  run_id          TEXT        -- 1:1 with runs.id, created by the enqueuer
  repo            TEXT        -- owner/repo
  issue           INTEGER
  role            TEXT
  trigger         TEXT
  workspace_key   TEXT        -- owner/repo#issue (Stage 3 lease key)
  state           TEXT        -- queued | leased | running | done | failed | reaped
  outcome         TEXT        -- success | no_op | error | timeout   (mirrors runs.outcome)
  error           TEXT
  pid             INTEGER
  host            TEXT
  claimed_at      TIMESTAMPTZ
  heartbeat_at    TIMESTAMPTZ
  deadline_at     TIMESTAMPTZ -- claimed_at + ROLE_TIMEOUT_SECONDS
  attempts        INTEGER DEFAULT 0
  created_at      TIMESTAMPTZ
  finished_at     TIMESTAMPTZ
```

`jobs` is the completion record the graph waits on. `runs` stays exactly what it
is — the human-facing observability row — so the Console needs no change to keep
working.

Claiming is a single atomic statement (`UPDATE ... WHERE state='queued' AND id IN
(SELECT ... ORDER BY created_at LIMIT n FOR UPDATE SKIP LOCKED)` on Postgres;
the existing read-then-conditional-update pattern from `claim_pending` on
SQLite).

### 2.2 The worker process

New module `factory_orchestrator/worker.py`, new console script
`factory-worker`. Its loop:

1. Claim a job (respecting admission control, §2.4).
2. Fork/exec nothing — the worker *is* the process that runs the role. Set
   `pid`, `host`, `claimed_at`, `deadline_at`; state → `running`.
3. Heartbeat thread: `UPDATE jobs SET heartbeat_at=now() WHERE id=?` every 10s
   for the life of the run.
4. Run the existing `execute_role(engine, item)` body **unchanged in substance**
   — guards, model resolution, `RoleRunner.run`, observer, `LiveRunLog`,
   `finish_run`. This is a move, not a rewrite.
5. On exit: state → `done`/`failed`, `outcome`, `finished_at`.

`execute_role` moves out of `graph.py` into `role_job.py` so both the worker and
the tests can import it without pulling in LangGraph.

### 2.3 The graph enqueues and waits

`run_role_node` becomes:

```python
def run_role_node(item: RunItem) -> dict[str, Any]:
    job = engine.jobs.enqueue(item)          # creates runs row + jobs row
    summary = engine.jobs.join(job.id)       # blocks on the record, not the process
    return {"completed": [summary]}
```

`join` polls `jobs` (1–2s) and returns when the row reaches a terminal state.
While waiting it enforces liveness rather than a naive timeout:

- `heartbeat_at` older than `HEARTBEAT_GRACE` (default 90s) **and** the pid is
  not alive on this host → the worker died; the joiner marks the job `reaped`,
  clears `factory:in-progress`, finishes the run as `error` with a real reason,
  and returns `status="error"` so `chain_node` refuses to chain architect. It
  does *not* silently retry: a half-finished role may have pushed a branch.
- `now() > deadline_at` → the same path with `status="timeout"`.

The graph thread is now cheap: it holds no subprocess, no workspace, no
semaphore slot. `Send` fan-out still gives real parallelism because N graph
threads wait on N job rows.

Because the join is a poll over the ledger, **the joiner is replaceable**: if
the API restarts mid-wait, the delivery is requeued, the graph re-invokes, and
`enqueue` finds an existing non-terminal job for `(repo, issue, role, round)` and
joins that one instead of starting a second. That single idempotency rule is
what makes "restart the orchestrator without killing the run" true.

### 2.4 Admission control moves to the queue

Delete the in-process `RoleRunner._slots` semaphore. The worker claims at most
`WORKER_CONCURRENCY` jobs, and the claim query enforces the per-repo cap that
`Engine.max_parallel(port)` currently computes and throws away: at most
`runners.max_parallel` jobs in `running` for a given repo. This is the first
time the repo's declared cap actually binds.

### 2.5 Orphan reaping on restart

`requeue_processing()` today is a blunt instrument — it re-queues every
`processing` delivery, including ones whose role is alive in a worker. Replace
with a startup reaper:

- Deliveries in `processing` whose jobs are all terminal or absent → `pending`.
- Deliveries in `processing` with a live job (fresh heartbeat, live pid) → left
  alone; the re-invoked graph rejoins the existing job.
- Jobs in `running` with a stale heartbeat → `reaped`: clear
  `factory:in-progress`, finish the run as `error`, release the workspace lease
  (Stage 3), and re-queue the delivery once (`attempts` bounded at 2).

### 2.6 Deployment shape

`docker-compose.yml` gains a `worker` service from the same image with
`command: factory-worker`, sharing `DATABASE_URL` and a **shared
`TRANSCRIPT_DIR` volume** (the API serves transcripts the worker writes). The
worker needs its own GitHub App credentials: `RoleRunner` receives
`engine.app.installation_token(...)`, and a token minted by the API at enqueue
time (50-minute cache TTL) can expire inside a 45-minute run. The worker mints
its own, with the Console's `/api/orchestrator/github-token` as the refresh path.

`WORKER_CONCURRENCY` and `worker` replicas become the scaling dial. Scale the
API for webhooks, the workers for roles.

### 2.7 Exit criterion

`docker compose kill orchestrator` mid-run:

- the `claude` process keeps running and `commands.test` still executes;
- the Console run page keeps advancing (worker writes, API is only a reader —
  restart it and the log resumes);
- restarting the API rejoins the in-flight job rather than starting a second;
- planner→architect chaining still holds, verified by the existing
  `tests/test_graph.py` chain assertions running unchanged against the new
  enqueue/join node.

---

## 3. Stage 3 — Workspace manager (state, not tempfile)

**Goal:** every checkout is a row. No anonymous temp dirs.

### 3.1 The record

```
workspaces
  key            TEXT PK     -- owner/repo#issue, == the LangGraph thread id
  repo           TEXT
  issue          INTEGER
  path           TEXT
  host           TEXT
  state          TEXT        -- absent|cloning|ready|running|idle|stale|deleting
  lease_job_id   TEXT        -- the one job allowed in the tree
  lease_pid      INTEGER
  lease_expires  TIMESTAMPTZ
  heartbeat_at   TIMESTAMPTZ
  size_bytes     BIGINT
  last_role      TEXT
  created_at     TIMESTAMPTZ
  updated_at     TIMESTAMPTZ
```

| State | Meaning |
| --- | --- |
| `absent` | nothing on disk |
| `cloning` | first fetch in progress |
| `ready` | tree exists, not leased |
| `running` | leased to one role worker |
| `idle` | role finished, PR may be open |
| `stale` | TTL expired or heartbeat missed |
| `deleting` | GC in progress |

The key is deliberately the LangGraph thread id, so a workspace, a thread, a
run history and an issue are all the same identity.

### 3.2 Leasing

`WorkspaceManager.acquire(key, job_id, pid)` is one conditional UPDATE:

```sql
UPDATE workspaces SET state='running', lease_job_id=?, lease_pid=?,
       lease_expires=now()+interval, updated_at=now()
 WHERE key=? AND state IN ('ready','idle') AND lease_job_id IS NULL
```

Zero rows updated → someone holds it → the job waits (it does not clone a
second tree). Two roles can never share a dirty tree, which the current design
prevents only by never sharing anything.

`release(key, outcome)` sets `idle` (Stage 4) or `deleting` (Stage 3, below).
A lease is renewed by the same heartbeat that renews the job.

### 3.3 Token hygiene

Today `clone_workspace` writes the installation token into `.git/config` and
relies on `rmtree` to destroy it. Two changes:

1. **Do not persist it at all.** Clone and fetch with the credential supplied
   per-invocation — `git -c http.extraHeader="Authorization: Basic <b64>" clone
   https://github.com/owner/repo` (or a `GIT_ASKPASS` shim), so `origin` is a
   plain URL from the first byte.
2. **Belt and braces:** on `release`, `git remote set-url origin
   https://github.com/owner/repo` and assert no `x-access-token` survives
   anywhere under `.git/`.

(1) is the fix; (2) is the check that keeps it true, and it is what makes a
long-lived tree in Stage 4 acceptable at all.

### 3.4 Deletion policy is unchanged in Stage 3

`release` still deletes after a successful push, exactly as the observer does
today. Stage 3 changes *who knows about the directory*, not how long it lives.
This keeps the blast radius to the manager itself: if the state machine is
wrong, the worst outcome is the same tempdir behaviour with a row beside it.

The reaper from §2.5 gains a workspace arm: rows in `running` whose
`lease_expires` has passed and whose `lease_pid` is dead → `stale` → kill any
surviving process group → `deleting` → gone. Rows on disk with no DB row (a
pre-Stage-3 leak) are logged and removed on boot.

### 3.5 Exit criterion

`GET /workspaces` lists every checkout on the box with path, state, lease
holder, pid, heartbeat and size; `find $WORKSPACE_ROOT -maxdepth 1` returns
nothing that is not in that list; a `kill -9` of a worker leaves a row that the
reaper moves `running → stale → deleting → absent` without operator action.

---

## 4. Stage 4 — Reuse until the PR merges

**Goal:** the second role on `#214` does not `git clone`.

### 4.1 Policy change

- After a green push: `release(key)` → **`idle`**, not deleted.
- Next role for the same key: `acquire` returns the existing tree; the worker
  runs a **prepare** routine instead of a clone.
- Delete when: the issue's factory PR is **merged**; or **closed without merge**
  plus a grace period (default 2h); or **idle TTL** (default 24–48h); or **disk
  pressure**.

### 4.2 Prepare is the risk, so it is explicit

A reused tree that carries junk from the last role produces a role failure that
looks like a model failure. `prepare()` is a fixed, tested sequence:

```
git remote set-url origin <plain url>          # then fetch with an ephemeral header
git fetch --prune --tags origin
git checkout --detach origin/<default-branch>
git reset --hard origin/<default-branch>
git clean -ffdx -e <preserved paths>
```

Preserved paths are exactly the ones reuse exists to keep: dependency caches
(`node_modules`, `.venv`, `~/.cache` under the workspace `HOME`) and, from
Stage 5, `.claude`. Everything else goes. If `prepare` fails for any reason the
manager does not attempt a repair: the workspace goes `stale`, is deleted, and
the job re-clones. Falling back to the Stage 3 behaviour must always be one
step away.

### 4.3 The sweeper

A periodic job (fold into the existing reconciler thread in `main.py`, or run it
in the worker so it survives an API restart) walks `idle` and `stale` rows and:

- asks GitHub for the factory PR on that issue — merged → `deleting`;
- closed-unmerged past grace → `deleting`;
- `updated_at` past `WORKSPACE_IDLE_TTL` → `deleting`;
- heartbeat missed while `running` → `stale` → kill → `deleting`.

Then, if total `size_bytes` exceeds `WORKSPACE_DISK_CAP`, evict `idle` rows
oldest-first until under the cap. Disk pressure never touches a `running` lease
— a full disk fails the newest job, it does not corrupt a live one.

### 4.4 Exit criterion

Two consecutive roles on the same issue: the second's run log shows a fetch, not
a clone, and starts measurably faster. Merging the factory PR makes the
directory disappear within one sweeper interval. With no PR ever opened, the TTL
does the same.

---

## 5. Stage 5 — Optional: session continuity

Only after 1–4 are boring.

Note that the plumbing is already half there: `RoleRunner` sets
`HOME=str(workspace)`, so `~/.claude` — including session state — is written
*inside* the workspace and is thrown away with it today. Once Stage 4 keeps the
tree and `prepare` preserves `.claude`, continuity is a matter of recording the
session id on the workspace row and passing `--resume <id>` (or a packed summary
of the last transcript) to the next `claude -p`.

Risks are real and are why this is last: stale context leaking a previous role's
assumptions into the next one, prompt growth against `MAX_TURNS`, and a
poisoned session that fails every subsequent role on the issue. Gate it behind
`WORKSPACE_SESSION_CONTINUITY=1`, per-repo, with an automatic fall back to a
cold prompt when a resumed run fails.

---

## 6. Console: making the processes visible

The Console today answers "how is run X going". Stages 2–4 create three new
things an operator needs to see, so the orchestrator exposes them and the
Console renders them.

### 6.1 New orchestrator endpoints (dispatch-token protected)

| Endpoint | Returns |
| --- | --- |
| `GET /queue` | pending/processing deliveries, depth, oldest age |
| `GET /jobs?state=` | job rows: role, issue, state, pid, host, heartbeat age, elapsed, remaining |
| `GET /jobs/{id}` + `POST /jobs/{id}/cancel` | detail; cancel kills the process group and finishes the run as cancelled |
| `GET /workspaces` | workspace rows: key, state, path, size, lease, age, last role |
| `POST /workspaces/{key}/release` / `DELETE /workspaces/{key}` | operator escape hatches |
| `GET /workers` | worker heartbeats: host, pid, concurrency, jobs in flight |

### 6.2 A "Factory ops" page

One page, three panes, one refresh loop (2s):

- **Queue** — depth, oldest waiting delivery, failed deliveries with their
  ledger error (the `public_delivery_error` text is already operator-facing).
- **Workers** — one card per live job: repo#issue, role, phase (from the
  existing `guards.phase`), elapsed vs remaining wall clock, pid/host,
  heartbeat age with a stale indicator, and a link to the existing run log.
- **Workspaces** — one row per key: state chip, size, lease holder, idle age,
  PR link, and the actions above.

The run log page stays exactly as it is. The new page answers the different
question — *what is this box doing* — and links into the old one for *how is
that going*.

Details of the Console-side work, including where it sits in the shell, are in
`software-factory-view` → `docs/plan/10-factory-ops-view.md`.

---

## 7. Sequencing and risk

| Stage | Ships | Reversible by |
| --- | --- | --- |
| 2 | jobs table, `factory-worker`, enqueue/join, reaper, worker service | running the worker in-process (`WORKER_INLINE=1`) |
| 3 | workspaces table, lease, token hygiene, workspace reaper | delete-on-release is already the Stage 3 policy |
| 4 | idle reuse, prepare, sweeper, disk cap | `WORKSPACE_REUSE=0` → Stage 3 behaviour |
| 5 | session continuity | `WORKSPACE_SESSION_CONTINUITY=0` |

Each stage keeps a flag back to the previous one. That matters because the
failure modes here are slow and non-obvious — a leaked token in a
month-old `.git/config`, a dirty tree that fails one role in twenty — and the
cheapest response to any of them is to turn the stage off while it is fixed.

**Ordering constraint:** Stage 4 depends on Stage 3's lease, and Stage 3's
reaper depends on Stage 2's heartbeat. Do not reorder. Stage 2 without Stage 3
is useful on its own (survivable runs, real scaling); Stage 3 without Stage 2 is
not (nothing to lease against).

### Things that will bite

- **Shared `TRANSCRIPT_DIR`.** The API serves files the worker writes. Same host
  or shared volume until run events move into the database. Note this before the
  first multi-host deployment, not after.
- **Token lifetime.** A 45-minute role against a token minted at enqueue time.
  The worker must mint and refresh its own.
- **Double-start on restart.** The enqueue idempotency key
  `(repo, issue, role, round)` is what stops it. Test it explicitly.
- **`factory:in-progress` outliving its run.** Today a `finally` guarantees the
  clear. Across processes only the reaper can guarantee it. Treat the reaper's
  label-clearing as a first-class requirement, not cleanup.
- **Stage 4 hygiene.** Every reuse bug will present as a role failure. Log the
  full `prepare` output into the run transcript so the run log shows the tree it
  started from.
