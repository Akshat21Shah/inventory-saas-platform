# Developer commands (CLAUDE.md §8). Run `make help` for the list.
SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND_VENV := backend/.venv
# Relative to backend/ (every backend command runs `cd backend && ...`); works with spaces in paths.
PY := .venv/bin
# Host-run backend commands (tests, schema export) use the migration owner role.
OWNER_DB_URL := postgres://app_owner:app_owner@localhost:5432/inventory

.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps migrate makemigrations seed shell test test-backend test-frontend e2e-stack e2e-responsive lan localhost \
        e2e lint lint-backend lint-frontend fmt api-client db-up check-schema

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env

setup: .env ## Install local toolchains (backend venv via uv, web node_modules)
	test -x $(BACKEND_VENV)/bin/uv || (python3 -m venv $(BACKEND_VENV) && $(BACKEND_VENV)/bin/pip install -q uv)
	cd backend && $(PY)/uv sync --frozen
	cd web && npm ci

up: .env ## Start the full stack (postgres, redis, mailpit, s3, backend, worker, beat, web)
	$(COMPOSE) up -d --build
	@echo "web:      http://localhost:3000   (tenants: http://{slug}.localhost:3000, admin: http://admin.localhost:3000)"
	@echo "api:      http://localhost:8000/api/v1/docs/   health: http://localhost:8000/health/ready"
	@echo "mailpit:  http://localhost:8025   s3 (SeaweedFS): http://localhost:8333"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail logs of all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

db-up: .env ## Start only postgres + redis (for host-run tests)
	$(COMPOSE) up -d postgres redis

migrate: ## Apply migrations (as the schema owner role)
	$(COMPOSE) run --rm migrate

makemigrations: ## Create migrations (host venv, owner role)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py makemigrations

seed: ## Load demo data (super admin, 2 tenants: staff, 20 shops, 200 products, prices, stock, orders each)
	$(COMPOSE) exec backend python manage.py seed

shell: ## Django shell inside the backend container
	$(COMPOSE) exec backend python manage.py shell

test: test-backend test-frontend ## Backend + frontend tests

test-backend: db-up ## pytest (needs postgres; uses the owner role to create the test DB)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/pytest

test-frontend: ## vitest
	cd web && npm test

e2e: ## Playwright (starts the web dev server if not running)
	cd web && npx playwright test

e2e-stack: ## Acceptance E2E against the running stack (after make up + make seed)
	cd web && E2E_FULL_STACK=1 E2E_BASE_URL=http://localhost:3000 npx playwright test --workers=1 e2e/acceptance.spec.ts e2e/catalog-acceptance.spec.ts e2e/pricing-tools.spec.ts e2e/inventory-acceptance.spec.ts e2e/orders-acceptance.spec.ts e2e/billing-acceptance.spec.ts e2e/notifications-acceptance.spec.ts e2e/compliance-acceptance.spec.ts

lan: ## Open the dev stack to phones on your Wi-Fi via <lan-ip>.nip.io (undo: make localhost)
	infra/dev-domain.sh lan

localhost: ## Serve the dev stack on *.localhost again (this Mac only)
	infra/dev-domain.sh localhost

e2e-responsive: ## Every screen at 360/768/1440 px (after make up + make seed); screenshots in web/test-results/responsive
	cd web && E2E_FULL_STACK=1 E2E_BASE_URL=http://localhost:3000 npx playwright test --workers=1 --project=desktop e2e/responsive.spec.ts

lint: lint-backend lint-frontend ## ruff, mypy, eslint, tsc, prettier

lint-backend:
	cd backend && $(PY)/ruff check . && $(PY)/ruff format --check . && $(PY)/mypy .

lint-frontend:
	cd web && npm run lint && npm run typecheck && npm run format:check

fmt: ## Auto-format backend and frontend
	cd backend && $(PY)/ruff check --fix . && $(PY)/ruff format .
	cd web && npm run format

api-client: ## Export the OpenAPI schema and regenerate web/lib/api/generated
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py spectacular --file openapi.yaml --validate --fail-on-warn
	cd web && npm run api:generate

check-schema: ## Fail if the committed OpenAPI schema is out of date
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py spectacular --file /tmp/openapi.check.yaml --validate --fail-on-warn
	diff -u backend/openapi.yaml /tmp/openapi.check.yaml
