#!/usr/bin/env bash
# Install the orchestrator into a local virtualenv (./.venv).
#
# Works with pyenv, Homebrew, python.org or system Python: it looks for a
# Python 3.11+ interpreter itself and never relies on a bare `pip` being on
# the PATH (pyenv shims famously break that). Override the interpreter with
#   PYTHON=python3.12 ./scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# ---------------------------------------------------------- pick a python
PY=""
for candidate in "${PYTHON:-}" python3.12 python3.11 python3 python; do
  [ -n "$candidate" ] || continue
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo -e "${RED}No Python 3.11+ found on PATH.${NC}"
  echo "With pyenv:   pyenv global 3.12.0   (or: PYTHON=\$(pyenv which python3.12) ./scripts/install.sh)"
  echo "With brew:    brew install python@3.12"
  exit 1
fi
echo -e "${GREEN}Using $($PY -V) at $(command -v "$PY")${NC}"

# ---------------------------------------------------------- venv + install
if [ ! -d .venv ]; then
  echo -e "${YELLOW}Creating virtualenv at ./.venv${NC}"
  "$PY" -m venv .venv
fi
./.venv/bin/python -m pip install --quiet --upgrade pip
echo -e "${YELLOW}Installing factory-orchestrator (editable, with dev deps)${NC}"
./.venv/bin/python -m pip install -e ".[dev]"

echo ""
echo -e "${GREEN}✓ Installed into ./.venv${NC}"
echo ""
echo "The make targets and scripts pick up ./.venv automatically:"
echo "  make test    make dev    make smoke    ./deploy.sh local health"
echo ""
echo "To use it directly:  source .venv/bin/activate"
