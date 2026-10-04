# Developer commands (CLAUDE.md §8). Run `make help` for the list.
SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND_VENV := backend/.venv
# Relative to backend/ (every backend command runs `cd backend && ...`); works with spaces in paths.
PY := .venv/bin
# Host-run backend commands (tests, schema export) use the migration owner role.
OWNER_DB_URL := postgres://app_owner:app_owner@localhost:5432/inventory

.DEFAULT_GOAL := help
.PHONY: help setup secrets-scan up down logs ps migrate makemigrations seed seed-volume perf perf-exports shell test test-backend test-frontend e2e-stack e2e-responsive lan localhost webhook-tunnel \
        e2e lint lint-backend lint-frontend fmt api-client db-up check-schema messages

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env

setup: .env ## Install local toolchains (backend venv via uv, web node_modules)
	test -x $(BACKEND_VENV)/bin/uv || (python3 -m venv $(BACKEND_VENV) && $(BACKEND_VENV)/bin/pip install -q uv)
	cd backend && $(PY)/uv sync --frozen
	cd web && npm ci
	cd mobile && npm ci
	cd backend && $(PY)/uv run pre-commit install  # hooks incl. the secrets scan (ADR-055)

secrets-scan: ## Scan the whole git history (every branch) for secrets with gitleaks (ADR-055)
	docker run --rm -v "$(CURDIR)":/repo:ro zricethezav/gitleaks:v8.30.1 git /repo \
		--log-opts="--all" --config /repo/.gitleaks.toml --redact --no-banner

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

seed-volume: ## Speed-check data: 3 test distributors (vol-a/b/c) with 40,000 / 5,000 / 5,000 orders over a year
	$(COMPOSE) exec backend python manage.py seed_volume

perf: ## Dashboard + every report's first page over the last whole month (p95 < 300 ms), global search (p95 < 200 ms) and the purchasing pages (after make seed-volume)
	$(COMPOSE) exec backend python manage.py perf_reports --last-month
	$(COMPOSE) exec backend python manage.py perf_search

perf-exports: ## The heaviest background exports: time and memory (after make seed-volume)
	$(COMPOSE) exec backend python manage.py perf_exports

shell: ## Django shell inside the backend container
	$(COMPOSE) exec backend python manage.py shell

test: test-backend test-frontend ## Backend + frontend tests

test-backend: db-up ## pytest (needs postgres; uses the owner role to create the test DB)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/pytest

test-frontend: ## vitest
	cd web && npm test

e2e: ## Playwright (starts the web dev server if not running)
	cd web && npx playwright test

e2e-stack: ## Acceptance E2E (Phases 1-9, 11a) against the running stack (after make up + make seed)
	cd web && E2E_FULL_STACK=1 E2E_BASE_URL=http://localhost:3000 npx playwright test --workers=1 e2e/acceptance.spec.ts e2e/catalog-acceptance.spec.ts e2e/pricing-tools.spec.ts e2e/inventory-acceptance.spec.ts e2e/orders-acceptance.spec.ts e2e/billing-acceptance.spec.ts e2e/notifications-acceptance.spec.ts e2e/compliance-acceptance.spec.ts e2e/reports-acceptance.spec.ts e2e/purchasing-acceptance.spec.ts e2e/growth-acceptance.spec.ts e2e/selfservice-acceptance.spec.ts e2e/ai-acceptance.spec.ts e2e/languages-acceptance.spec.ts

lan: ## Open the dev stack to phones on your Wi-Fi via <lan-ip>.nip.io (undo: make localhost)
	infra/dev-domain.sh lan

localhost: ## Serve the dev stack on *.localhost again (this Mac only)
	infra/dev-domain.sh localhost

webhook-tunnel: ## Dev only: a public https address for payment webhooks ONLY (Razorpay test mode; needs cloudflared)
	@python3 infra/webhook-relay.py 8765 & RELAY=$$!; trap "kill $$RELAY" EXIT INT TERM; \
	echo "Webhook URL = the https://….trycloudflare.com address below + the path under Settings → Online payments → Webhook address"; \
	cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765

e2e-responsive: ## Every screen at 360/768/1440 px (LANGUAGE=hi or mr for those; after make up + make seed); screenshots in web/test-results/responsive
	cd web && E2E_FULL_STACK=1 E2E_BASE_URL=http://localhost:3000 E2E_LANGUAGE=$(or $(LANGUAGE),en) npx playwright test --workers=1 --project=desktop e2e/responsive.spec.ts

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
	cd mobile && npm run api-client

messages: ## Update and compile the server message catalogs (backend/locale; then translate what it lists)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py messages

texts-export: ## Every screen, app, server and notification text in one sheet for translators (texts.xlsx)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py texts_export --out ../texts.xlsx

texts-import: ## Check a translator's sheet: make texts-import SHEET=reviewed.xlsx [APPLY=1] (writes the files)
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py texts_import $(abspath $(SHEET)) $(if $(APPLY),--apply,)

check-schema: ## Fail if the committed OpenAPI schema is out of date
	cd backend && DATABASE_URL=$(OWNER_DB_URL) $(PY)/python manage.py spectacular --file /tmp/openapi.check.yaml --validate --fail-on-warn
	diff -u backend/openapi.yaml /tmp/openapi.check.yaml

# --- Android shop app (mobile/, ADR-061) --------------------------------------------------------
# The app reaches the dev stack on the LAN address ("make lan"), like a phone on the same Wi-Fi.
MOBILE_DOMAIN := $(shell sed -n 's/^PLATFORM_DOMAIN=//p' infra/dev-domain.env 2>/dev/null)
MOBILE_ENV := ANDROID_HOME=$(HOME)/Library/Android/sdk JAVA_HOME=$$(/usr/libexec/java_home 2>/dev/null) \
	APP_API_URL=http://$(MOBILE_DOMAIN):3000 APP_PLATFORM_DOMAIN=$(MOBILE_DOMAIN) SENTRY_DISABLE_AUTO_UPLOAD=true

mobile-check: ## The app: lint, types, unit tests, files synced from the web
	cd mobile && npm run lint && npm run typecheck && npm test -- --ci && npm run check

mobile-sync: ## Copy the shared modules, the shop's texts and the design tokens from web/ into mobile/
	cd mobile && npm run sync

mobile-android: ## Development build on the running emulator or USB phone (needs make lan); then: cd mobile && npx expo start
	@test -n "$(MOBILE_DOMAIN)" || (echo "Run make lan first: the app reaches the stack on the LAN address" && exit 1)
	cd mobile && $(MOBILE_ENV) npx expo prebuild --platform android --clean && $(MOBILE_ENV) npx expo run:android --no-bundler

mobile-apk: ## An installable APK for a phone on this Wi-Fi (needs make lan): mobile/android/app/build/outputs/apk/release/
	@test -n "$(MOBILE_DOMAIN)" || (echo "Run make lan first: the app reaches the stack on the LAN address" && exit 1)
	cd mobile && $(MOBILE_ENV) npx expo prebuild --platform android --clean
	cd mobile/android && $(MOBILE_ENV) ./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a
	@ls -l mobile/android/app/build/outputs/apk/release/*.apk
