# Local development for the factory orchestrator. See README.md.
.PHONY: install test lint conformance dev smoke compose-up compose-down

install:            ## editable install with dev deps
	pip install -e ".[dev]"

test:               ## full test suite (includes the shared conformance fixtures)
	python3 -m pytest tests -q

lint:
	python3 -m ruff check src tests

conformance:        ## both engines against the shared routing fixtures
	python3 -m pytest tests/test_conformance.py tests/test_claim.py -q
	cd .. && node scripts/test-router.js

dev:                ## run the service on :8080 with sqlite and auto-reload
	./scripts/dev.sh

smoke:              ## signed-webhook smoke test against a running instance
	python3 scripts/smoke.py

compose-up:         ## full stack (orchestrator + Postgres) — needs .env
	docker compose up --build -d && docker compose logs -f orchestrator

compose-down:
	docker compose down
