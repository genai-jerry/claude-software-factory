#!/bin/bash
# deploy.sh - local/server compose deployment, lighthouse-backend style.
#
#   ./deploy.sh [environment] [action]
#
# environment picks the env file: config.<environment>.env (falling back to
# .env, created from .env.example if missing). Actions mirror lighthouse's
# deploy.sh, plus orchestrator-specific `health` and `smoke`.

set -e
cd "$(dirname "$0")"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Factory Orchestrator Deployment ===${NC}"
echo ""

# Parse arguments
ENVIRONMENT=${1:-local}
ACTION=${2:-up}

# Pick the env file: config.<env>.env wins; else .env (seeded from the example)
ENV_FILE="config.${ENVIRONMENT}.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE=".env"
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}Error: neither config.${ENVIRONMENT}.env nor .env found${NC}"
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo -e "${YELLOW}Created .env. Please edit it (GitHub App, Anthropic credential) before deploying.${NC}"
        echo ""
    fi
fi

echo -e "${YELLOW}Loading environment from ${ENV_FILE}${NC}"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo -e "${YELLOW}Environment: $ENVIRONMENT${NC}"
echo -e "${YELLOW}Action: $ACTION${NC}"
echo ""

# Execute action
case $ACTION in
    up|start)
        echo -e "${GREEN}Starting services...${NC}"
        docker compose up -d
        echo ""
        echo -e "${GREEN}✓ Services started${NC}"
        ;;
    down|stop)
        echo -e "${YELLOW}Stopping services...${NC}"
        docker compose down
        echo ""
        echo -e "${GREEN}✓ Services stopped${NC}"
        ;;
    restart)
        echo -e "${YELLOW}Restarting services...${NC}"
        docker compose restart
        echo ""
        echo -e "${GREEN}✓ Services restarted${NC}"
        ;;
    logs)
        echo -e "${YELLOW}Showing logs (Ctrl+C to exit)...${NC}"
        docker compose logs -f
        ;;
    status|ps)
        echo -e "${YELLOW}Container status:${NC}"
        docker compose ps
        ;;
    build)
        echo -e "${YELLOW}Building images...${NC}"
        docker compose build --no-cache
        echo -e "${GREEN}✓ Images built${NC}"
        ;;
    rebuild)
        echo -e "${YELLOW}Rebuilding and restarting...${NC}"
        docker compose up -d --build
        echo -e "${GREEN}✓ Rebuilt and restarted${NC}"
        ;;
    health)
        echo -e "${YELLOW}Checking service health...${NC}"
        if curl -fsS "http://localhost:${PORT:-8080}/healthz"; then
            echo ""
            echo -e "${GREEN}✓ Service is healthy${NC}"
        else
            echo -e "${RED}✗ Health check failed${NC}"
            docker compose logs --tail 50 orchestrator || true
            exit 1
        fi
        ;;
    smoke)
        echo -e "${YELLOW}Running signed-webhook smoke test...${NC}"
        PY=python3
        [ -x .venv/bin/python ] && PY=.venv/bin/python
        "$PY" scripts/smoke.py "http://localhost:${PORT:-8080}"
        ;;
    *)
        echo -e "${RED}Unknown action: $ACTION${NC}"
        echo ""
        echo "Usage: ./deploy.sh [environment] [action]"
        echo ""
        echo "Environments: local (default), staging, production"
        echo "  Env file: config.<environment>.env, falling back to .env"
        echo ""
        echo "Actions:"
        echo "  up, start   - Start services"
        echo "  down, stop  - Stop services"
        echo "  restart     - Restart services"
        echo "  logs        - View logs"
        echo "  status, ps  - Show status"
        echo "  build       - Build images"
        echo "  rebuild     - Rebuild and restart"
        echo "  health      - Curl the /healthz endpoint"
        echo "  smoke       - Signed-webhook smoke test"
        echo ""
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Deployment complete!${NC}"

# Show access URLs
echo ""
echo -e "${YELLOW}Access URLs:${NC}"
echo "  Health:   http://localhost:${PORT:-8080}/healthz"
echo "  Runs:     http://localhost:${PORT:-8080}/runs"
echo "  Webhook:  http://localhost:${PORT:-8080}/webhooks/github"
echo ""
