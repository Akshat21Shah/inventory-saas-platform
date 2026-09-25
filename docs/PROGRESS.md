# Progress

## Done
- 2026-09-24 — Master plan `docs/PLAN.md`; product-owner decisions applied (PLAN v1.1, SPEC v1.1, ADR-001…019).
- 2026-09-25 — Follow-up answers applied (PLAN v1.2, SPEC updates, ADR-020…022).
- 2026-09-25 — Phase 0 merged to `main` (PR #1).
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
- CI: **green on GitHub Actions** for branch `phase-0-foundation`: backend, frontend, e2e and image builds (run 36095584513).

## Review follow-ups (2026-09-25)
- SeaweedFS approved for local dev/CI only; production uses AWS S3.
- Project moved to a path without spaces.
  - The backend venv was recreated.
  - Makefile venv paths stay relative to `backend/` (harmless; independent of the absolute path).
  - `make up` and `make test` were re-verified.
- S3 bucket init made idempotent and race-free on cold start.
- The root layout no longer depends on generated `LayoutProps` types, so a clean checkout type-checks.
- Signing keys are >= 32 bytes in CI and `.env.example`; prod settings refuse shorter keys.
- CI actions are on Node 24 versions, and CI runs on pushes to any branch.
- The Claude Code deny rule (`mcp__bex`) now lives in the committed `.claude/settings.json`; `.claude/settings.local.json` is untracked (per-developer only).
- The status line in `PLAN.md` now says Phase 0 is complete.

## In progress
- **Phase 1 — Tenancy, auth, platform admin** (branch `phase-1`; plan approved 2026-09-25, including the wider PLAN §8 scope).
  - Decisions recorded: ADR-025 … ADR-031; PLAN v1.3 (§1.2 T7, §2.2, §2.3, §3.2, §9.1/§9.2 Security keys, §10).
  - Done so far:
    - Field-level encryption (ADR-031).
    - Platform models: full `Tenant` with GSTIN/PAN/state/slug check constraints; `State` (GST codes), `TaxRate`, `CessType`, `HsnRateHint`; tenant-owned `TenantProfile` (encrypted bank account), `TenantBranding`, `Subscription` and `TenantFeature` with RLS; `Plan` (Beta default) and `FeatureFlag` (8, all off). Selectors: cached `effective_features` / `is_feature_enabled`, `current_plan`, `plan_limit_allows`. The Phase 0 dev tenants are backfilled by migration, and the seed creates complete demo tenants.
    - The master-data APIs (tax rates, cess types, HSN hints) move to the platform-API commit, after permissions and audit exist.
  - Deferred to later phases: invoice series (5), GST/gateway credentials (7), `ws-ticket` (4), platform dashboard KPIs (8), notification templates (6). Retailer is a stub until Phase 2.

## Next
- Phase 1 commits, in order:
  1. ~~Encryption~~, ~~platform models and masters~~ (done)
  2. Storage adapter (moved next to branding assets)
  3. Audit log
  4. Settings registry
  5. Permissions and roles
  6. Staff auth
  7. 2FA and passwords
  8. Retailer OTP
  9. Invitations
  10. Onboarding and platform APIs
  11. Tenant settings and branding
  12. Impersonation and Django admin
  13–16. Frontend
  17. Seed, E2E and docs

## Known issues / pending
- ADR-009 (tax engine & rounding) is pending CA confirmation, needed before Phase 5.
- Production domain to be supplied before staging (ADR-019).
- Next.js dev-server redirects built from `request.url` use the dev server's own host when the Host header is forged (curl). Real browsers are unaffected. Revisit if a reverse proxy sits in front in dev.
