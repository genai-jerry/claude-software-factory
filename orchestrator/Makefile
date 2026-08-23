# Local development for the factory orchestrator. See README.md.
#
# `make install` creates ./.venv (scripts/install.sh — pyenv/brew/system
# friendly, no bare `pip` needed); every other target uses that venv when it
# exists and falls back to python3 otherwise.
.PHONY: install test lint conformance dev smoke compose-up compose-down

PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

install:            ## create ./.venv and install with dev deps
	./scripts/install.sh

test:               ## full test suite (includes the shared conformance fixtures)
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests

conformance:        ## both engines against the shared routing fixtures
	$(PY) -m pytest tests/test_conformance.py tests/test_claim.py -q
	cd .. && node scripts/test-router.js

dev:                ## run the service on :8080 with sqlite and auto-reload
	./scripts/dev.sh

smoke:              ## signed-webhook smoke test against a running instance
	$(PY) scripts/smoke.py

compose-up:         ## full stack (orchestrator + Postgres) — needs .env
	docker compose up --build -d && docker compose logs -f orchestrator

compose-down:
	docker compose down
