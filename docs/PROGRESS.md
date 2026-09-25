# Progress

## Done
- 2026-09-24 — Master plan `docs/PLAN.md`; product-owner decisions applied (PLAN v1.1, SPEC v1.1, ADR-001…019).
- 2026-09-25 — Follow-up answers applied (PLAN v1.2, SPEC updates, ADR-020…022).
- 2026-09-25 — **Phase 0 — Foundation** implemented and verified:
  - **Infra**
    - Docker Compose: postgres 16 (three roles: owner / runtime without BYPASSRLS / platform with BYPASSRLS), redis, mailpit, SeaweedFS S3 + bucket init, a one-shot `migrate` service, backend (uvicorn ASGI), celery worker, celery beat, web.
    - Dev/prod Dockerfiles; Makefile; `.env.example`.
  - **Backend** (`backend/`)
    - Settings: base/dev/test/prod from env. DRF, drf-spectacular (`/api/v1/schema/`, `/api/v1/docs/`), simplejwt scaffolding, Channels (`/ws/v1/ping/`), Celery (+ beat schedule), CORS.
    - JSON logging with request_id / tenant_id / user_id; Sentry (DSN-gated); `/health/live` and `/health/ready`; public `/api/v1/meta/`.
    - `common` building blocks:
      - UUIDv7 ids; Money/Qty/Rate/UnitCost fields and Decimal helpers.
      - `TenantScopedModel` + fail-closed `TenantManager`; tenant contextvar; JWT `tid` claim → context + `SET LOCAL app.current_tenant`.
      - `EnableRLS` and `MakeAppendOnly` migration operations.
      - Error envelope + error-code registry, with rollback on every handled error.
      - Cursor pagination; base permissions (fail closed); host classification.
      - Sequences (gap-free); idempotency keys; transactional outbox + sweeper; `retry_on_deadlock`; `TenantTask`.
      - Isolation-coverage harness; seed skeleton.
    - Stubs: `platform.Tenant`, `accounts.User` (completed in Phase 1).
  - **Frontend** (`web/`, Next.js 16)
    - Tailwind v4 + shadcn/ui; design tokens with a per-tenant brand palette derived from one colour.
    - next-intl (`messages/en.json`); TanStack Query; generated API client (orval, `make api-client`).
    - Shared components: DataTable, EmptyState, ErrorState, PageHeader, StatusBadge, MoneyText/QtyText/DateText, ConfirmDialog, skeletons, FormField.
    - Shells for `/platform`, `/manage` and `/shop` (bottom nav, PWA manifest, service worker, offline page); host-aware `proxy.ts`; `/design-system` page; Sentry (DSN-gated).
  - **Quality**
    - ruff, mypy (strict), eslint, prettier, tsc strict.
    - pytest: 57 tests, including the RLS backstop, RLS-on-every-tenant-table, append-only, concurrent idempotency, outbox and rollback tests.
    - vitest: 37 tests, including a check that every backend error code has an i18n message.
    - Playwright: 4 tests (desktop + 360px).
    - pre-commit; GitHub Actions CI (backend, frontend, e2e, image builds).

## Phase 0 acceptance
- `make up` runs everything: all services up; backend healthy; worker online; beat dispatching the outbox sweeper.
- Health checks pass, directly and through the web proxy.
- Design system page renders every core component in all states, with no horizontal scroll at 360px.
- CI: the workflow is written and every step passes locally. It has **not run on GitHub yet** because nothing is pushed.

## In progress
- Nothing. Awaiting review of Phase 0.

## Next
- Phase 1 — Tenancy, auth, platform admin (PLAN §8).

## Known issues / pending
- ADR-009 (tax engine & rounding) is pending CA confirmation, needed before Phase 5.
- Production domain to be supplied before staging (ADR-019).
- MinIO images are unavailable; SeaweedFS is used instead (ADR-024). Confirm this is acceptable.
- Next.js dev-server redirects built from `request.url` use the dev server's own host when the Host header is forged (curl). Real browsers are unaffected. Revisit if a reverse proxy sits in front in dev.
