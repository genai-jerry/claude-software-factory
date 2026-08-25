# Local Packaging & Deployment (no GitHub Actions)

`orchestrator/scripts/local-deploy.sh` packages and deploys the LangGraph
orchestrator from your machine, the same way
[`lighthouse-backend/scripts/local-deploy.sh`](https://github.com/genai-jerry/lighthouse-backend/blob/main/scripts/local-deploy.sh)
deploys the CRM. It replicates `.github/workflows/deploy-orchestrator.yml`
so no GitHub Actions minutes are spent:

1. Verifies this repo is the **latest `origin/main`** (production) or
   `origin/staging` (staging).
2. Fetches GitHub **variables** (`PUBLIC_BASE_URL`, `CLAIMED_REPOS`,
   `FACTORY_REPO`, `FACTORY_REF`) via `gh`.
3. Loads **secrets** from a local env file.
4. Builds the `linux/amd64` `factory-orchestrator` image, SCPs the tarball
   plus `orchestrator/infra/docker-compose.deploy.yml` to
   `~/factory-orchestrator` on the VPS, and runs the same remote script CI
   uses: load image → upsert `.env` → `docker compose up` → wait until the
   `factory-orchestrator` container is healthy → prune.

Factory Console has a sibling script: `software-factory-view/scripts/local-deploy.sh`.

This is **not** `orchestrator/deploy.sh`, which drives `docker compose` on
the machine you are already on (laptop or a shell already on the VPS).

## Prerequisites

- Docker (Apple Silicon works — the script builds for `linux/amd64`).
- [GitHub CLI](https://cli.github.com) authenticated: `gh auth login`.
- SSH private key for the Hostinger VPS (same trio as Factory Console).

## One-time setup

```bash
cd orchestrator
./scripts/local-deploy.sh production --init-secrets
# then edit ~/.lighthouse-deploy/factory-orchestrator.production.env
```

You can copy `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_KEY_FILE` from
`~/.lighthouse-deploy/factory-console.production.env`. The App private key
is `FACTORY_GH_APP_PRIVATE_KEY_B64` (`base64 -i app.pem`, no wraps).
`DISPATCH_TOKEN` must match Console `ORCHESTRATOR_DISPATCH_TOKEN`.

## Deploying

```bash
git checkout main && git pull origin main
cd orchestrator
./scripts/local-deploy.sh production
```

Useful flags: `--show-config`, `--build-only`, `--no-fetch-vars`,
`--skip-git-check`, `--secrets-file <path>`. Env knobs: `DEPLOY_KEY_FILE`,
`DEPLOY_PORT`, `DEPLOY_PLATFORM` (default `linux/amd64`).

## How GitHub configuration is fetched

**Variables** are readable and exported automatically. Environment-level
values override repo-level ones.

**Secrets** (`DEPLOY_*`, `FACTORY_GH_*`, `DISPATCH_TOKEN`, Anthropic tokens)
**cannot be fetched**. They live in
`~/.lighthouse-deploy/factory-orchestrator.<env>.env`. Empty optional keys
are skipped on the host so existing `.env` entries survive.

Resolution order (later wins): shell environment → GitHub variables →
secrets file.

## Stop spending on Actions

```bash
gh workflow disable "Deploy Factory Orchestrator" -R genai-jerry/claude-software-factory
```

Re-enable later with `gh workflow enable`.

## Troubleshooting

- **`gh: Not Found (404)` fetching environment variables** — check
  `gh api repos/genai-jerry/claude-software-factory/environments --jq '.environments[].name'`.
- **`exec format error` on the VPS** — leave `DEPLOY_PLATFORM=linux/amd64`.
- **orchestrator never becomes healthy** — the script prints compose `ps`
  and the last 100 orchestrator log lines.
- **No Anthropic credential** — allowed if the Console forwards a token on
  `POST /events`. Otherwise role runs will fail at model resolve.
