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

## Test locally on your laptop

No Docker, GitHub App, or Postgres needed for the first loop:

```bash
cd orchestrator
make install        # pip install -e ".[dev]"
make test           # 116 tests, including the shared routing fixtures
make conformance    # both engines against the fixtures (needs node + js-yaml)
make dev            # http://localhost:8080 — sqlite, auto-reload, dev fallbacks
make smoke          # from another terminal: signed webhook, dedupe, bad-sig checks
```

`make dev` boots with placeholder credentials so the intake path (signature
verification, idempotency ledger, queue, `/runs`, `/healthz`) is fully
exercisable before any real registration. For the full loop on a laptop:

1. Copy `.env.example` → `.env` and fill in a real GitHub App
   (`GITHUB_APP_PRIVATE_KEY_B64` = `base64 -w0 < key.pem`) and an Anthropic
   credential. Set `FACTORY_LOCAL_PATH` to your factory checkout to skip the
   factory clone while iterating on role prompts.
2. GitHub cannot reach `localhost`, so bridge webhooks with
   [smee.io](https://smee.io): create a channel, set it as the App's webhook
   URL, and run `npx smee-client --url https://smee.io/<channel> --target
   http://localhost:8080/webhooks/github`.
3. Claim a scratch repo (`.github/factory-orchestrator.json` →
   `"engine": "langgraph"`), file a test issue, and watch
   `curl localhost:8080/runs` plus the labels move on the issue.

`make compose-up` runs the production shape (image + Postgres) when you do
have Docker locally.

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
   | `CONSOLE_DATABASE_URL`, `CONSOLE_MASTER_KEY`, `CONSOLE_ORG` | optional — read agent secrets the Factory Console retained (below) |

### Agent secrets from the Factory Console

Agent secrets entered in the Factory Console (`software-factory-view`) —
`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `FACTORY_CROSS_REPO_TOKEN`
— are written through to each repo's GitHub Actions secrets *and retained*,
sealed in the Console's `orchestrator_secrets` table. Point the
orchestrator at that store with `CONSOLE_DATABASE_URL` (the Console's
Postgres) and `CONSOLE_MASTER_KEY` (the same key the Console seals with;
`CONSOLE_ORG` only when the Console hosts more than one org), and:

- values the deployment did not set by env come from the store — you can
  drop the Anthropic credential from the deploy secrets entirely and manage
  it in the Console UI instead;
- env vars always win when both are set;
- rotations in the Console reach role runs on the next refresh cycle
  (reconciler timer, ~15 min; restart to force) — no redeploy;
- a temporarily unreachable Console store never interrupts running work.

The Console's API stays write-only for these values (metadata out, never
secrets); the orchestrator is the only reader, via the shared master key.

3. **Run**: `docker compose up` (orchestrator + Postgres), or
   `pip install -e . && factory-orchestrator` against your own database.
   `GET /healthz` is the health endpoint.

### Deploy to a VPS (Hostinger) — the lighthouse-backend way

`.github/workflows/deploy-orchestrator.yml` deploys exactly the way
`lighthouse-backend`'s `deploy.yml` does: build the image on the runner,
`docker save | gzip`, SCP the tarball to the host, then over SSH — load,
stop/rm the old container, write the env file from environment-scoped
secrets, `docker run` on a shared docker network, health-check via
`docker exec curl`, prune. It triggers on pushes to `main` touching
`orchestrator/**`, or manually via *Run workflow* with an environment
choice.

One-time setup:

1. Create the `production` (and optionally `staging`) GitHub Environment on
   this repo and add, per the comment block at the top of the workflow:
   - **Secrets**: `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_KEY` (the same
     SSH trio lighthouse uses), `FACTORY_GH_APP_ID`,
     `FACTORY_GH_APP_PRIVATE_KEY_B64`, `FACTORY_GH_WEBHOOK_SECRET`
     (GitHub forbids secret names starting with `GITHUB_`),
     `ANTHROPIC_API_KEY` *or* `CLAUDE_CODE_OAUTH_TOKEN`, `DISPATCH_TOKEN`;
     optional `FACTORY_CROSS_REPO_TOKEN`, `ORCH_DATABASE_URL`.
   - **Variables**: `PUBLIC_BASE_URL` (required), `CLAIMED_REPOS`,
     `DOCKER_NETWORK` (default `factory-network`), `PUBLISH_PORT`
     (e.g. `127.0.0.1:8080:8080` when nginx runs on the host itself; leave
     empty when the reverse-proxy container shares the docker network, as
     in the lighthouse setup).
2. Point HTTPS at the container: either a host nginx/caddy proxying the
   published port, or attach your existing proxy container to
   `DOCKER_NETWORK` and route to `factory-orchestrator-production:8080`.
   `PUBLIC_BASE_URL` and the GitHub App's webhook URL are that address.
3. Push to `main` (or *Run workflow*). The container gets a named volume at
   `/data` (sqlite database + transcripts survive redeploys); set
   `ORCH_DATABASE_URL` to a Postgres URL instead when you outgrow sqlite.

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
