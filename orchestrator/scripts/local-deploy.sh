#!/usr/bin/env bash
set -euo pipefail

# Local packaging + deployment for the LangGraph factory orchestrator.
#
# Replicates .github/workflows/deploy-orchestrator.yml from a local machine
# the same way lighthouse-backend/scripts/local-deploy.sh does:
#   1. Verifies the factory repo checkout is the latest origin/main (or staging).
#   2. Fetches GitHub *variables* via gh.
#   3. Loads *secrets* from a local env file.
#   4. Builds the linux/amd64 image from orchestrator/, SCPs it with
#      infra/docker-compose.deploy.yml, and runs the same remote script CI uses.
#
# Configuration precedence (later wins):
#   shell environment  <  GitHub variables  <  secrets file

REPO="genai-jerry/claude-software-factory"

usage() {
  cat <<'EOF'
Usage: ./scripts/local-deploy.sh [production|staging] [options]

Builds the factory-orchestrator image locally and deploys it to the Hostinger
VPS with docker compose, replicating .github/workflows/deploy-orchestrator.yml
without GitHub Actions. Run this from the orchestrator/ directory.

Options:
  --secrets-file <path>  Env file with secret values
                         (default: ~/.lighthouse-deploy/factory-orchestrator.<env>.env)
  --init-secrets         Write a template secrets file and exit
  --show-config          Print resolved configuration (secrets masked) and exit
  --build-only           Build and save the image tarball, skip transfer/deploy
  --no-fetch-vars        Skip the gh CLI variable fetch (fully offline mode)
  --skip-git-check       Deploy the working tree as-is (dirty/non-main allowed)
  -h, --help             Show this help

Extra knobs (env vars): DEPLOY_KEY_FILE, DEPLOY_PORT (default 22),
DEPLOY_PLATFORM (default linux/amd64 — needed when building on arm64 Macs).

Config precedence (later wins): shell env < GitHub variables < secrets file.
EOF
}

log()  { echo "[local-deploy] $*"; }
warn() { echo "[local-deploy] WARNING: $*" >&2; }
die()  { echo "[local-deploy] ERROR: $*" >&2; exit 1; }

host_from_url() {
  local u="${1-}"
  u="${u#http://}"
  u="${u#https://}"
  u="${u%%/*}"
  u="${u%%:*}"
  printf '%s' "$u"
}

# Empty $1 = current repo. Non-empty = git -C <root> (this script lives under orchestrator/).
check_git_for_deploy() {
  local g=(git)
  [[ -n "${1:-}" ]] && g=(git -C "$1")
  log "Verifying checkout against origin/${GIT_BRANCH}..."
  "${g[@]}" fetch origin "$GIT_BRANCH"
  [[ -z "$("${g[@]}" status --porcelain)" ]] || \
    die "Working tree has uncommitted changes. Commit/stash them or pass --skip-git-check."
  local head remote
  head="$("${g[@]}" rev-parse HEAD)"
  remote="$("${g[@]}" rev-parse "origin/${GIT_BRANCH}")"
  if [[ "$head" == "$remote" ]]; then
    :
  elif "${g[@]}" merge-base --is-ancestor "$remote" "$head"; then
    warn "HEAD is $("${g[@]}" rev-list --count "$remote..HEAD") commit(s) ahead of origin/${GIT_BRANCH} — deploying this checkout (not yet on GitHub). git push when you want origin to match."
  elif "${g[@]}" merge-base --is-ancestor "$head" "$remote"; then
    die "HEAD is behind origin/${GIT_BRANCH}. Run: git checkout ${GIT_BRANCH} && git pull origin ${GIT_BRANCH}"
  else
    die "HEAD has diverged from origin/${GIT_BRANCH}. Rebase or merge, or pass --skip-git-check."
  fi
  log "OK — deploying $("${g[@]}" rev-parse --short HEAD) ($("${g[@]}" log -1 --format=%s))"
}

TARGET_ENV="production"
SECRETS_FILE=""
INIT_SECRETS=false
SHOW_CONFIG=false
BUILD_ONLY=false
FETCH_VARS=true
SKIP_GIT_CHECK=false

while (($#)); do
  case "$1" in
    production|staging) TARGET_ENV="$1"; shift ;;
    --secrets-file)     SECRETS_FILE="$2"; shift 2 ;;
    --init-secrets)     INIT_SECRETS=true; shift ;;
    --show-config)      SHOW_CONFIG=true; shift ;;
    --build-only)       BUILD_ONLY=true; shift ;;
    --no-fetch-vars)    FETCH_VARS=false; shift ;;
    --skip-git-check)   SKIP_GIT_CHECK=true; shift ;;
    -h|--help)          usage; exit 0 ;;
    *)                  die "Unknown argument: $1 (see --help)" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCH_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ORCH_DIR/.." && git rev-parse --show-toplevel)"
cd "$ORCH_DIR"

SECRETS_FILE="${SECRETS_FILE:-$HOME/.lighthouse-deploy/factory-orchestrator.${TARGET_ENV}.env}"
SECRETS_FILE="${SECRETS_FILE/#\~/$HOME}"

if [[ "$TARGET_ENV" == "production" ]]; then GIT_BRANCH="main"; else GIT_BRANCH="staging"; fi

DOCKER_IMAGE="factory-orchestrator"
IMAGE_TAR="factory-orchestrator.tar.gz"
DEPLOY_PLATFORM="${DEPLOY_PLATFORM:-linux/amd64}"

# GitHub forbids secret names starting GITHUB_; FACTORY_GH_* map to GITHUB_* on the VPS.
GH_SECRET_NAMES=(DEPLOY_HOST DEPLOY_USER DEPLOY_KEY
                 FACTORY_GH_APP_ID FACTORY_GH_APP_PRIVATE_KEY_B64 FACTORY_GH_WEBHOOK_SECRET
                 DISPATCH_TOKEN ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN
                 FACTORY_CROSS_REPO_TOKEN)
GH_VAR_NAMES=(PUBLIC_BASE_URL ORCHESTRATOR_HOST CLAIMED_REPOS FACTORY_REPO FACTORY_REF)
REQUIRED=(DEPLOY_HOST DEPLOY_USER FACTORY_GH_APP_ID FACTORY_GH_APP_PRIVATE_KEY_B64
          FACTORY_GH_WEBHOOK_SECRET DISPATCH_TOKEN PUBLIC_BASE_URL)

if $INIT_SECRETS; then
  [[ -e "$SECRETS_FILE" ]] && die "Refusing to overwrite existing ${SECRETS_FILE}"
  mkdir -p "$(dirname "$SECRETS_FILE")"
  umask 077
  {
    echo "# Secret values for factory-orchestrator '${TARGET_ENV}' local deploys."
    echo "# GitHub never returns secret values, so mirror them here by hand."
    echo "# Keep this file OUT of git. chmod 600 is applied automatically."
    echo "# Same SSH trio as Factory Console / lighthouse-backend."
    echo
    echo "DEPLOY_HOST="
    echo "DEPLOY_USER="
    echo "DEPLOY_KEY_FILE=~/.ssh/id_rsa"
    echo "#DEPLOY_PORT=22"
    echo
    echo "# GitHub App (base64 -i app.pem — no wraps)."
    echo "FACTORY_GH_APP_ID="
    echo "FACTORY_GH_APP_PRIVATE_KEY_B64="
    echo "FACTORY_GH_WEBHOOK_SECRET="
    echo
    echo "# Must match Factory Console ORCHESTRATOR_DISPATCH_TOKEN."
    echo "DISPATCH_TOKEN="
    echo
    echo "# Optional — omit if Console forwards the token on POST /events:"
    echo "#ANTHROPIC_API_KEY="
    echo "#CLAUDE_CODE_OAUTH_TOKEN="
    echo "#FACTORY_CROSS_REPO_TOKEN="
    echo
    echo "# Variables (fetched from GitHub unless you set them here):"
    echo "#PUBLIC_BASE_URL=https://factory.genaipeople.com"
    echo "#CLAIMED_REPOS=genai-jerry/insurance-app-base"
    echo "#FACTORY_REPO=genai-jerry/claude-software-factory"
    echo "#FACTORY_REF=v1"
  } > "$SECRETS_FILE"
  log "Template written to ${SECRETS_FILE} — fill in the values, then re-run the deploy."
  exit 0
fi

if ! $SKIP_GIT_CHECK; then
  check_git_for_deploy "$REPO_ROOT"
fi

FETCHED_VARS=""
fetch_var_endpoint() {
  local endpoint="$1" out line name value
  if ! out="$(gh api "$endpoint" --paginate --jq '.variables[] | "\(.name)=\(.value|@base64)"' 2>&1)"; then
    warn "Could not fetch ${endpoint}: ${out}"
    return 0
  fi
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    name="${line%%=*}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="$(printf '%s' "${line#*=}" | base64 --decode)"
    export "${name}=${value}"
    FETCHED_VARS="${FETCHED_VARS}${FETCHED_VARS:+ }${name}"
  done <<< "$out"
}

if $FETCH_VARS; then
  command -v gh >/dev/null 2>&1 || \
    die "gh CLI not found. Install it (https://cli.github.com) and run 'gh auth login', or pass --no-fetch-vars."
  gh auth status >/dev/null 2>&1 || die "gh CLI is not authenticated. Run: gh auth login"
  log "Fetching GitHub variables for ${REPO} (repo-level, then '${TARGET_ENV}' environment)..."
  fetch_var_endpoint "repos/${REPO}/actions/variables"
  fetch_var_endpoint "repos/${REPO}/environments/${TARGET_ENV}/variables"
  log "Fetched variables: ${FETCHED_VARS:-none}"
else
  log "Skipping GitHub variable fetch (--no-fetch-vars)."
fi

load_secrets_file() {
  local file="$1" line key value lineno=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" != *=* ]]; then
      warn "Ignoring malformed line ${lineno} in ${file} (expected KEY=VALUE)"
      continue
    fi
    key="${line%%=*}"
    value="${line#*=}"
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      warn "Ignoring invalid key on line ${lineno} in ${file}"
      continue
    fi
    if [[ ${#value} -ge 2 && ( "$value" == \"*\" || "$value" == \'*\' ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "${key}=${value}"
  done < "$file"
}

if [[ -f "$SECRETS_FILE" ]]; then
  log "Loading secrets from ${SECRETS_FILE}"
  chmod 600 "$SECRETS_FILE" 2>/dev/null || true
  load_secrets_file "$SECRETS_FILE"
else
  warn "Secrets file ${SECRETS_FILE} not found. Create it with: $0 ${TARGET_ENV} --init-secrets"
fi

FACTORY_GH_APP_ID="${FACTORY_GH_APP_ID:-${GITHUB_APP_ID:-${GH_APP_ID:-}}}"
FACTORY_GH_APP_PRIVATE_KEY_B64="${FACTORY_GH_APP_PRIVATE_KEY_B64:-${GITHUB_APP_PRIVATE_KEY_B64:-}}"
FACTORY_GH_WEBHOOK_SECRET="${FACTORY_GH_WEBHOOK_SECRET:-${GITHUB_WEBHOOK_SECRET:-${GH_WEBHOOK_SECRET:-}}}"

if [[ -z "${ORCHESTRATOR_HOST:-}" && -n "${PUBLIC_BASE_URL:-}" ]]; then
  ORCHESTRATOR_HOST="$(host_from_url "$PUBLIC_BASE_URL")"
fi
export ORCHESTRATOR_HOST PUBLIC_BASE_URL

missing=""
for var in "${REQUIRED[@]}"; do
  [[ -n "${!var:-}" ]] || missing="${missing} ${var}"
done
[[ -n "${DEPLOY_KEY:-}" || -n "${DEPLOY_KEY_FILE:-}" ]] || missing="${missing} DEPLOY_KEY|DEPLOY_KEY_FILE"
[[ -n "${ORCHESTRATOR_HOST:-}" ]] || missing="${missing} ORCHESTRATOR_HOST|PUBLIC_BASE_URL"
if [[ -n "$missing" ]]; then
  echo "Missing required configuration for ${TARGET_ENV}:${missing}" >&2
  echo "Secrets go in ${SECRETS_FILE}; variables come from GitHub (or the same file)." >&2
  if command -v gh >/dev/null 2>&1; then
    echo "Secret names configured in GitHub for reference (values are NOT retrievable):" >&2
    gh api "repos/${REPO}/environments/${TARGET_ENV}/secrets" --jq '.secrets[].name' 2>/dev/null | sed 's/^/  - /' >&2 || true
  fi
  exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  warn "No Anthropic credential in the secrets file — Console must send one on /events or /dispatch."
fi

export GITHUB_APP_ID="$FACTORY_GH_APP_ID"
export GITHUB_APP_PRIVATE_KEY_B64="$FACTORY_GH_APP_PRIVATE_KEY_B64"
export GITHUB_WEBHOOK_SECRET="$FACTORY_GH_WEBHOOK_SECRET"
export FACTORY_REPO="${FACTORY_REPO:-genai-jerry/claude-software-factory}"
export FACTORY_REF="${FACTORY_REF:-v1}"
export DATABASE_URL="${DATABASE_URL:-sqlite:////data/factory-orchestrator.db}"
export IMAGE_TAR

if $SHOW_CONFIG; then
  echo "Resolved configuration for ${TARGET_ENV}:"
  for name in "${GH_VAR_NAMES[@]}"; do printf '  %-32s= %s\n' "$name" "${!name:-}"; done
  for name in "${GH_SECRET_NAMES[@]}"; do
    [[ -n "${!name:-}" ]] && printf '  %-32s= <set>\n' "$name" || printf '  %-32s= <empty>\n' "$name"
  done
  printf '  %-32s= %s\n' "DEPLOY_KEY_FILE" "${DEPLOY_KEY_FILE:-}"
  exit 0
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
TAR_PATH="${WORK_DIR}/${IMAGE_TAR}"

log "Building ${DOCKER_IMAGE}:latest for ${DEPLOY_PLATFORM}..."
docker build --platform "$DEPLOY_PLATFORM" -t "${DOCKER_IMAGE}:latest" .

log "Saving image to ${IMAGE_TAR}..."
docker save "${DOCKER_IMAGE}:latest" | gzip > "$TAR_PATH"
cp infra/docker-compose.deploy.yml "${WORK_DIR}/docker-compose.yml"
log "Image tarball: $(du -h "$TAR_PATH" | cut -f1)"

if $BUILD_ONLY; then
  cp "$TAR_PATH" "./${IMAGE_TAR}"
  log "--build-only: image left at ./${IMAGE_TAR}; skipping transfer and deploy."
  exit 0
fi

if [[ -n "${DEPLOY_KEY_FILE:-}" ]]; then
  KEY_PATH="${DEPLOY_KEY_FILE/#\~/$HOME}"
  [[ -f "$KEY_PATH" ]] || die "DEPLOY_KEY_FILE ${KEY_PATH} does not exist."
else
  KEY_PATH="${WORK_DIR}/deploy_key"
  printf '%s\n' "$DEPLOY_KEY" > "$KEY_PATH"
  chmod 600 "$KEY_PATH"
fi
DEPLOY_PORT="${DEPLOY_PORT:-22}"
SSH_OPTS=(-i "$KEY_PATH" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30)

log "Preparing deploy directory on ${DEPLOY_HOST}..."
ssh "${SSH_OPTS[@]}" -p "$DEPLOY_PORT" "${DEPLOY_USER}@${DEPLOY_HOST}" \
  'set -euo pipefail; mkdir -p "$HOME/factory-orchestrator"'

log "Transferring image and compose file..."
scp "${SSH_OPTS[@]}" -P "$DEPLOY_PORT" "$TAR_PATH" \
  "${DEPLOY_USER}@${DEPLOY_HOST}:/tmp/${IMAGE_TAR}"
scp "${SSH_OPTS[@]}" -P "$DEPLOY_PORT" \
  "${WORK_DIR}/docker-compose.yml" \
  "${DEPLOY_USER}@${DEPLOY_HOST}:factory-orchestrator/docker-compose.yml"

REMOTE_ENVS=(ORCHESTRATOR_HOST PUBLIC_BASE_URL GITHUB_APP_ID GITHUB_APP_PRIVATE_KEY_B64
             GITHUB_WEBHOOK_SECRET DISPATCH_TOKEN ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN
             FACTORY_CROSS_REPO_TOKEN CLAIMED_REPOS FACTORY_REPO FACTORY_REF
             DATABASE_URL IMAGE_TAR)

REMOTE_SCRIPT="${WORK_DIR}/deploy-remote.sh"
{
  echo "set -euo pipefail"
  for v in "${REMOTE_ENVS[@]}"; do
    printf 'export %s=%q\n' "$v" "${!v:-}"
  done
  # Body below is copied from .github/workflows/deploy-orchestrator.yml "Deploy on host".
  cat <<'REMOTE_EOF'
if [ -z "${ORCHESTRATOR_HOST:-}" ]; then
  echo "ORCHESTRATOR_HOST is empty — set PUBLIC_BASE_URL on the GitHub Environment." >&2
  exit 1
fi

DEPLOY_DIR="$HOME/factory-orchestrator"
cd "$DEPLOY_DIR"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  sudo usermod -aG docker "$USER"
fi

docker load < "/tmp/${IMAGE_TAR:-factory-orchestrator.tar.gz}"
rm -f "/tmp/${IMAGE_TAR:-factory-orchestrator.tar.gz}"

touch .env
chmod 600 .env
for KEY in ORCHESTRATOR_HOST PUBLIC_BASE_URL GITHUB_APP_ID GITHUB_APP_PRIVATE_KEY_B64 \
           GITHUB_WEBHOOK_SECRET DISPATCH_TOKEN ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN \
           FACTORY_CROSS_REPO_TOKEN CLAIMED_REPOS FACTORY_REPO FACTORY_REF DATABASE_URL; do
  VALUE="${!KEY-}"
  [ -z "$VALUE" ] && continue
  TMP="$(mktemp)"
  grep -v "^${KEY}=" .env > "$TMP" || true
  printf '%s=%s\n' "$KEY" "$VALUE" >> "$TMP"
  mv "$TMP" .env
done
chmod 600 .env

docker network inspect lighthouse-network >/dev/null 2>&1 || \
  docker network create lighthouse-network

"${DC[@]}" up -d --remove-orphans

echo "Waiting for orchestrator to become healthy..."
for attempt in $(seq 1 60); do
  STATE=$(docker inspect -f '{{.State.Health.Status}}' factory-orchestrator 2>/dev/null || echo missing)
  if [ "$STATE" = "healthy" ]; then
    echo "orchestrator healthy"
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "orchestrator did not become healthy (last state: $STATE)" >&2
    "${DC[@]}" ps
    "${DC[@]}" logs --tail 100 orchestrator
    exit 1
  fi
  sleep 3
done

docker image prune -f >/dev/null || true
echo "Deployment completed. Orchestrator at https://${ORCHESTRATOR_HOST}/healthz"
echo "Console api/worker should use ORCHESTRATOR_URL=http://factory-orchestrator:8080"
REMOTE_EOF
} > "$REMOTE_SCRIPT"

log "Running deploy on ${DEPLOY_HOST}..."
ssh "${SSH_OPTS[@]}" -p "$DEPLOY_PORT" "${DEPLOY_USER}@${DEPLOY_HOST}" 'bash -s' < "$REMOTE_SCRIPT"

log "Done — factory orchestrator (${TARGET_ENV}) deployed from local machine."
