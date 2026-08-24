#!/usr/bin/env bash
# Run the orchestrator locally: sqlite storage, uvicorn with auto-reload.
# Reads .env if present (copy .env.example). No Docker, no Postgres needed.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# Safe dev fallbacks so the service boots before a real App is registered.
export GITHUB_APP_ID="${GITHUB_APP_ID:-000000}"
export GITHUB_APP_PRIVATE_KEY="${GITHUB_APP_PRIVATE_KEY:-dev-placeholder-key}"
export GITHUB_WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-dev-webhook-secret}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-sk-dev-placeholder}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///factory-orchestrator.db}"
export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:8080}"
# Console Re-run POSTs /dispatch; keep this in lockstep with
# software-factory-view's ORCHESTRATOR_DISPATCH_TOKEN (compose default).
export DISPATCH_TOKEN="${DISPATCH_TOKEN:-dev-dispatch-token}"

# Prefer the venv scripts/install.sh created; fall back to python3.
if [ -z "${PYTHON:-}" ] && [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
fi

echo "orchestrator dev server -> http://localhost:${PORT:-8080}  (healthz, /runs, /webhooks/github)"
echo "smoke-test it from another terminal:  make smoke"
exec "${PYTHON:-python3}" -m uvicorn --factory factory_orchestrator.devapp:create \
  --host 0.0.0.0 --port "${PORT:-8080}" --reload
