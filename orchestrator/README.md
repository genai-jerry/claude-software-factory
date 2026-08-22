# Factory Orchestrator (LangGraph engine)

The LangGraph orchestration engine for the [Claude Software
Factory](../FACTORY.md) — a long-lived service that drives the same
pipeline the GitHub Actions engine drives, for repos that opt in
(FACTORY.md §2e). GitHub stays the state machine, OpenSpec stays the
content; this service is only the motor: it receives GitHub App webhooks,
routes them with a Python port of the factory router (proven equivalent by
the shared fixtures in `conformance/`), and executes the factory roles as
headless Claude Code sessions in isolated workspaces.

```
GitHub webhook ► verify HMAC + idempotency ledger ► queue (DB-backed)
   ► StateGraph on thread owner/repo#issue:
       route ► claim check ► mark in-progress ► snapshot ► resolve model
             ► run role (fresh clone + claude -p) ► no-op guard ► clear marker
       └ chains as graph edges: planner→architect · G0 fan-out · re-dispatch
```

At a human gate the invocation ends — the parked position is the label on
GitHub, no compute waits, and the next webhook resumes the thread.

## Deploy

1. **Register a GitHub App** (Settings → Developer settings → GitHub Apps):
   - Webhook URL: `https://<your-host>/webhooks/github`, with a webhook secret.
   - Repository permissions: **Issues, Contents, Pull requests** read/write.
   - Subscribe to events: **Issues, Issue comment, Milestone, Push**.
   - Install it on every repo the orchestrator will drive; note the App ID
     and download the private key.
2. **Configure** — environment variables (see `docker-compose.yml`):

   | Variable | Meaning |
   |---|---|
   | `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | the App identity |
   | `ANTHROPIC_API_KEY` **or** `CLAUDE_CODE_OAUTH_TOKEN` | the credential role runs use |
   | `DATABASE_URL` | `postgresql+psycopg://…` (or `sqlite:///…` for a single-repo install) |
   | `PUBLIC_BASE_URL` | where this service is reachable — failure comments link `<base>/runs/<id>` |
   | `FACTORY_REPO`, `FACTORY_REF` | the factory source for FACTORY.md + role prompts (pin like the Actions stub pins `@v1`) |
   | `CLAIMED_REPOS` | comma-separated `owner/repo` list the reconciliation sweep covers |
   | `DISPATCH_TOKEN` | bearer token for the manual `/dispatch` endpoint |
   | `FACTORY_CROSS_REPO_TOKEN` | optional estate-wide PAT, same role as in Actions |
   | `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | optional — set them and LangGraph traces to LangSmith, unset and nothing changes |

3. **Run**: `docker compose up` (orchestrator + Postgres), or
   `pip install -e . && factory-orchestrator` against your own database.
   `GET /healthz` is the health endpoint.

## Claim a repo (migration runbook)

1. Install the GitHub App on the repo.
2. Open a PR adding `.github/factory-orchestrator.json` (template:
   `../templates/factory-orchestrator.json`) with `"engine": "langgraph"`;
   review and merge it to the default branch.
3. **Verify the stand-down**: trigger any factory event (comment on an
   issue) and check the Actions run for the caller stub — its route job
   must exit with *"Engine stand-down: … names \"langgraph\""* and do
   nothing. Leave the stub in place; it is your rollback path.
4. **Canary**: file a small test issue and watch it under the orchestrator
   (`GET /runs?repo=owner/repo`, plus the ordinary labels and comments on
   the issue — they are byte-identical to the Actions engine's traces).
   Drive it through one gate before trusting the repo to the engine.
5. Add the repo to `CLAIMED_REPOS` so the reconciliation sweep covers it.

**Rollback** is the same PR in reverse: set `"engine": "github-actions"`
(or delete the file) and merge. Actions resumes routing from the repo's
current labels on the next event. No state migrates in either direction —
GitHub carries all of it.

## Operating notes

- **Runs**: `GET /runs?repo=…&issue=…&active=true` lists runs;
  `GET /runs/<id>` one run; `GET /runs/<id>/transcript` the secret-redacted
  agent transcript. Failure comments on issues link here.
- **Manual dispatch** (the "Run workflow" equivalent):
  `POST /dispatch {"owner","repo","role","issue"}` with
  `Authorization: Bearer $DISPATCH_TOKEN`.
- **Missed events**: the reconciliation sweep (startup + every 15 min)
  re-queues approved gates whose follow-up role never ran and approved
  releases never fanned out. Everything it queues flows through the same
  idempotent router, so a double-detection is harmless.
- **Conformance**: `pytest tests/` runs the shared routing fixtures; a
  routing change is a change to `conformance/fixtures/` plus both engines,
  gated by `.github/workflows/conformance.yml`.

## Security posture

Identical to the Actions engine where it matters: gate G3 stays human-only
(agents run with the factory's protected-branch hook and cannot merge PRs),
approver lists are enforced router-side, the App token is scoped to claimed
repos and minted per run, and credentials reach roles only through the
environment — never prompts, ledgers, or transcripts (which are redacted).
