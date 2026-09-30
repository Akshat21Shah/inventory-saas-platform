# CLAUDE.md — Agent Working Rules

You are the lead engineer on a production B2B SaaS platform. Read this file fully at the start of every session. The complete product specification is in `docs/PROJECT_SPEC.md` — it is the source of truth for WHAT to build. This file defines HOW to build it.

## 1. Project in one paragraph

A multi-tenant inventory and B2B ordering platform. Our company (Super Admin) owns the platform. Distributors/dealers (Tenants) subscribe and manage products, stock, retailers, orders, GST invoices, payments and a ledger. Retailers (end clients, non-technical shop owners) belong to exactly one distributor, see only that distributor's catalog, and place orders (including backorders) from a mobile-first web app (PWA), and later an Android app.

## 2. Locked technology stack (do not change without an ADR in docs/DECISIONS.md)

- Backend: Python 3.12+, Django 5.x, Django REST Framework, drf-spectacular (OpenAPI), Celery + Redis, Django Channels, PostgreSQL 16 (+ pg_trgm, later pgvector)
- Frontend: Next.js (App Router) + TypeScript (strict) + Tailwind CSS + shadcn/ui, TanStack Query, React Hook Form + Zod, next-intl
- API client: generated from the OpenAPI schema (never hand-write API types)
- Mobile (later phase): React Native (Expo) using the same generated client
- Local dev: Docker Compose (postgres, redis, mailpit, backend, worker, beat, web)
- Monitoring: Sentry (backend + frontend), structured JSON logging
- Tests: pytest + pytest-django + factory_boy (backend), Vitest + Testing Library (frontend), Playwright (E2E)

## 3. How you work

1. **Plan before coding.** For every phase or non-trivial task, first write a short plan (files to create/change, models, endpoints, tests) and wait for approval if the user is present. Then implement.
2. **One phase at a time.** Follow the roadmap in `docs/PROJECT_SPEC.md` section 12. Do not start features from later phases. If something from a later phase is needed as a dependency, build the minimal stub and note it.
3. **Small, working increments.** Each commit leaves the app runnable with passing tests. Use conventional commits (`feat(orders): ...`, `fix(inventory): ...`).
4. **Keep docs current.** After each task update `docs/PROGRESS.md` (done / in progress / next / known issues). Record any significant design decision as an ADR in `docs/DECISIONS.md`.
5. **Ask, don't guess, on business rules.** If the spec is ambiguous about money, tax, stock or permissions, stop and ask. For purely technical choices, choose the simplest robust option and document it.
6. **Verify before claiming done.** Run migrations, the test suite, linters and type checks. Never say "done" with failing tests or unrun code.
7. **Never fabricate** external API details (GST/GSP, WhatsApp, payment gateways). Implement behind an adapter interface with a mock/sandbox implementation and leave a clearly marked TODO with what must be verified against official docs.

## 4. Non-negotiable engineering rules

### Tenant isolation (highest priority)
- Every tenant-owned model inherits `TenantScopedModel` (has `tenant` FK, indexed) and uses a manager that auto-filters by the current tenant.
- The current tenant is resolved once per request (from the authenticated user; subdomain only for branding/public pages) and stored in a context variable. Celery tasks receive `tenant_id` explicitly and set the context.
- PostgreSQL Row-Level Security is enabled on tenant tables as a backstop, using `SET LOCAL app.current_tenant`.
- Every API endpoint has a test proving a user from tenant A cannot read or modify tenant B data.
- Super Admin cross-tenant access goes through explicit, audited code paths only.

### Money and tax
- Use `Decimal` everywhere (`DecimalField(max_digits=14, decimal_places=2)`, quantities `decimal_places=3`). Never use float for money, tax or quantity.
- Rounding rules live in ONE module (`apps/billing/tax.py`) and are unit tested exhaustively.
- Ledger entries and stock movements are append-only. Corrections are new reversing entries, never edits or deletes.

### Stock correctness
- All stock changes go through `apps/inventory/services.py` inside `transaction.atomic()` with `select_for_update()` on the affected stock rows, locked in a consistent order (by product id) to avoid deadlocks.
- `quantity_on_hand` and `quantity_reserved` have DB check constraints (`>= 0`).
- Every change writes a `StockMovement` row in the same transaction.
- Include a concurrency test: two simultaneous orders for the last unit must never both reserve it.

### Reliability
- Order placement and payment endpoints require an `Idempotency-Key` header; duplicates return the original result.
- Anything calling an external service (email, WhatsApp, SMS, GSP, payment gateway, PDF storage) runs in a Celery task with retries + exponential backoff, and never blocks or rolls back the core business transaction. Use `transaction.on_commit()` to enqueue.
- Every external integration sits behind an adapter interface with at least a `mock` implementation used in dev and tests.
- Payment status changes only from verified gateway webhooks (signature checked), never from client callbacks alone.
- Feature flags (per tenant) gate optional modules: payments, subscriptions enforcement, e-invoice, e-way bill, WhatsApp, batches/expiry, multi-warehouse, AI features.

### Thin client
- ALL business logic (pricing, discounts, credit checks, tax, stock availability, backorder split, permissions) is computed on the server. Frontends only render server results and send user intent. Never compute a price or tax in the frontend.

### Security
- RBAC checked on the server for every endpoint (DRF permission classes). Frontend hiding is cosmetic only.
- Secrets from environment / secrets manager only. Tenant credentials (payment gateway keys, GSP credentials) are encrypted at rest (field-level encryption).
- Rate limiting on auth/OTP endpoints. Validate all input with serializers. Restrict uploads by type and size.
- Audit log for sensitive actions (price changes, stock adjustments, credit limit changes, order accept/reject, impersonation, settings changes).

## 5. Backend code structure

```
backend/
  config/                 settings (base/dev/test/prod), urls, asgi, celery
  apps/<module>/
    models.py             data only, no business logic
    services.py           ALL write/business logic (functions, typed, transactional)
    selectors.py          read/query logic
    api/serializers.py    validation + representation only
    api/views.py          thin: permission -> serializer -> service/selector -> response
    api/urls.py
    tasks.py              Celery tasks (thin, call services)
    adapters/             external integrations (interface + implementations)
    events.py             domain events emitted by services
    tests/
  common/                 base models, tenant context, permissions, pagination, exceptions, money utils
```
- Type hints on all service/selector functions. Views never touch the ORM for writes.
- Consistent error format: `{ "error": { "code": "CREDIT_LIMIT_EXCEEDED", "message": "...", "details": {...} } }` with stable machine-readable codes the frontend maps to translated messages.
- All list endpoints are paginated, filterable and use `select_related`/`prefetch_related`. Add DB indexes starting with `tenant_id` for tenant queries.
- Store timestamps in UTC; display in Asia/Kolkata.
- API versioned under `/api/v1/`.

## 6. Frontend code structure and UX rules

```
web/
  app/(auth)/  app/(platform)/  app/(distributor)/  app/(retailer)/
  components/ui/          shadcn primitives (design system)
  components/shared/      app-level components (DataTable, EmptyState, StatusBadge, MoneyText...)
  lib/api/                GENERATED client + TanStack Query hooks
  lib/i18n/  messages/en.json hi.json mr.json
```
- Build the design system first (tokens, typography, spacing, components) and reuse it everywhere. Tenant branding is applied via CSS variables loaded from the server.
- Every data screen has loading (skeleton), empty, and error states. Users never see raw technical errors or stack traces.
- Retailer UI: mobile-first, large touch targets (min 44px), plain language (no "SKU", "tenant", "payload"), max ~3 taps from search to placed order, clear availability badges, "Repeat last order".
- Distributor UI: dashboard opens on "what needs action today". Tables support search, filters, bulk actions and export.
- All user-facing strings go through i18n keys from day one (English first; Hindi and Marathi files added later).
- Accessibility: semantic HTML, keyboard navigable, sufficient contrast, labelled inputs.
- Regenerate the API client after any backend API change; never edit generated files.

## 6a. Responsive design (every screen, phone to laptop)

Every screen works at three widths, and CI checks them: **360 px** (phone), **768 px** (tablet) and **1440 px** (laptop). Build with these shared patterns instead of one-off layouts:

- **Lists are cards on phones and tablets** (below 1024 px), tables on laptops. `DataTable` does this. Each list passes a `cardLayout` naming its fields:
  - `title`: the card heading, usually a link to the detail page.
  - `media`: a photo.
  - `primary`: a few `label: value` lines that are always shown.
  - `secondary`: behind "More", or only on the detail page.
  - `actions`: the row's buttons.

  Pick the 3–5 fields a person needs to recognise and act on a row (products: photo, name, code, price, status; retailers: shop name, owner, mobile, price list, status). Never stack every column.
- **Bulk actions use `DataTable`'s `selection`.** On laptops that's a checkbox column with an inline bar. On phones and tablets a "Select" button turns on checkboxes and the actions move to a bar fixed to the bottom of the screen. Row actions (edit, menus, dialogs) go in the `actions` slot and must work on a card.
- **Filters use `FilterBar`.** On phones the search stays visible and the other filters open in a bottom sheet from a "Filters (n)" button. On wider screens they sit inline.
- **Long forms end with `FormActions`.** It gives Save/Cancel a bar stuck to the bottom of the screen on phones and a normal row elsewhere. The settings registry form keeps its fixed save bar.
- **Touch targets are at least 44 × 44 px on phones.** The design-system primitives (Button, Input, Select, menu items, Tabs, Checkbox and Switch hit areas) already do this below 768 px, so don't shrink them with fixed heights on phones. Links inside running text are the only exception.
- **No sideways scrolling of the page, ever.** Wide content (tables on laptops, chip rows) scrolls inside its own `overflow-x-auto` container. No control may sit off-screen or overlap another.
- **Layout switches in code use `lib/use-media.ts`** (`useIsPhone` below 768 px, `useIsCompact` below 1024 px). Everything else uses Tailwind breakpoints (`max-md:`, `md:`, `lg:`).
- **The shop** is mobile-first: a bottom navigation bar on phones and tablets, navigation in the header on laptops, and a centred content column up to 1152 px wide.
- **Checks:**
  - Each new screen is added to `web/e2e/responsive.spec.ts`. It fails on sideways scrolling, off-screen or overlapping controls, and phone targets under 44 px, and saves a screenshot of every screen at every width (the CI artifact `responsive-screenshots`; locally `make e2e-responsive`).
  - Component tests can render at any width with `setViewport(width)` from `tests/viewport.ts`.

## 7. Definition of done (every task)

- [ ] Matches the spec; ambiguities raised, not guessed
- [ ] Migrations created and applied cleanly
- [ ] Unit tests for services (happy path + edge cases + permission + tenant isolation)
- [ ] API documented via drf-spectacular; client regenerated
- [ ] UI has loading/empty/error states, i18n keys, and follows §6a: listed in `e2e/responsive.spec.ts`, passing at 360/768/1440 px
- [ ] Lint, format, type checks pass (ruff, mypy, eslint, tsc)
- [ ] `docs/PROGRESS.md` updated

## 8. Commands (keep this section updated as the project evolves)

```
make setup       # local toolchains: backend/.venv (uv sync) + web/node_modules (npm ci)
make up          # docker compose up: postgres, redis, mailpit, s3 (SeaweedFS), migrate, backend, worker, beat, web
make down        # stop the stack            make logs / make ps   # logs / status
make db-up       # only postgres + redis (for host-run tests)
make migrate     # run migrations (as the schema-owner DB role)
make makemigrations
make test        # backend (pytest, needs postgres) + frontend (vitest)
make e2e         # Playwright (desktop + 360px)
make e2e-stack   # acceptance E2E (Phases 1-7) against the running stack (needs make up + make seed)
make e2e-responsive # every screen at 360/768/1440 px + screenshots (needs make up + make seed)
make lint        # ruff, ruff format --check, mypy, eslint, tsc, prettier --check
make fmt         # auto-format backend + frontend
make api-client  # export backend/openapi.yaml and regenerate web/lib/api/generated
make check-schema # fail if backend/openapi.yaml is stale
make seed        # demo data: super admin (+ dev 2FA key), 2 tenants, staff per role, 20 shops, 200 products with photos, price lists, discounts, stock, 11 orders, invoices, payments, a credit note and a refund each
make lan         # open the dev stack to phones on your Wi-Fi: http://{slug}.<lan-ip-with-dashes>.nip.io:3000
make localhost   # back to *.localhost (run before the E2E suites)
```

URLs in dev:
- web: http://localhost:3000 (tenant: http://{slug}.localhost:3000; admin: http://admin.localhost:3000)
- API docs: http://localhost:8000/api/v1/docs/
- health: http://localhost:8000/health/ready
- mailpit: http://localhost:8025 (emails, and copies of what the mock WhatsApp and SMS providers "send": `[WhatsApp mock] …`, `[SMS mock] …`)
- S3: http://localhost:8333
- After `make lan` (dev only): the same pages on `<lan-ip-with-dashes>.nip.io`, e.g. http://sharma.192-168-0-106.nip.io:3000. Only web (3000) and photos (8333) are reachable from other devices; database, Redis, API and Mailpit stay on this machine. `*.localhost` doesn't work until `make localhost`.
- Camera barcode scanning over `make lan` (dev only, ADR-041): browsers allow the camera only on https or localhost. On an Android phone, open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, enter the tenant address (e.g. `http://sharma.192-168-0-106.nip.io:3000`; several are separated by commas), choose Enabled and relaunch Chrome. iPhones have no such switch. Typed codes and USB/Bluetooth scanners work without it; real camera testing is on staging (https).

Database roles:
- `app_user` is the runtime role, with RLS enforced.
- `app_owner` runs migrations and tests.
- `app_platform` has BYPASSRLS and is reserved for audited platform paths.
