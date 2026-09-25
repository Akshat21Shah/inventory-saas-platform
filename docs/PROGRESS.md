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
    - Settings registry (`apps/platform/registry.py`): 28 tenant keys (PLAN §9.1 plus `security.require_staff_2fa`) and 10 platform keys (PLAN §9.2 plus the ADR-030 security limits). `TenantSetting` (RLS) and `PlatformSetting` store overrides only. Selectors give typed, cached reads and `settings_snapshot()`. Services do atomic batch set and reset, audited as `settings.changed` / `settings.reset`, with cache invalidation only after commit.
    - Permissions: code registry (`apps/accounts/permissions.py`) with 33 tenant codes and 8 platform codes, and system roles OWNER, MANAGER, SALES, WAREHOUSE, ACCOUNTS and PLATFORM_ADMIN, seeded and kept in sync (`sync_permissions`). `Role` (system roles have no tenant; RLS makes them readable by every tenant and writable by none), `Membership` (RLS), `User.platform_role`. `has_permission_code` resolves by the active tenant's membership. The test encodes the PLAN §3.1 matrix literally, and another test rejects unknown permission codes on any endpoint. `tenant_context` no longer masks DB errors.
    - Staff auth: `POST /api/v1/auth/staff/login/`, `staff/choose-tenant/`, `handoff/exchange/`, `token/refresh/`, `logout/`, and `GET/PATCH me/`.
      - Host rules (ADR-020): admin host accepts platform users only; a tenant subdomain accepts staff with an active membership there; on the generic domain, staff always get a 60-second handoff to their tenant subdomain, with a chooser if they belong to more than one tenant. The plan's "tokens directly when there is one membership" was dropped so refresh cookies stay host-scoped (ADR-020).
      - Every credential failure returns the same `INVALID_CREDENTIALS`. Lockout: 5 failures lock for 15 minutes (audited, with an email). Rate limits per IP and per email come from platform settings (ADR-030).
      - Tokens (ADR-025): access JWT in memory; refresh in an httpOnly, host-only, `SameSite=Lax` cookie with `Path=/api/v1/auth/`; rotation is race-free (row lock) and blacklists the old token; lifetimes are 12 h for super admin, 7 d for staff (fixed at sign-in) and 30 d sliding for retailers; the password hash in each token means a password change revokes everything. Cookie endpoints require `X-Requested-With: fetch` and a matching `Origin`.
      - Every request re-checks tenant status, active membership and token/host match, so suspension and deactivation take effect at once.
      - API routes use trailing slashes, like the Phase 0 routes.
    - 2FA and passwords:
      - TOTP (`pyotp`): the secret is encrypted, each time step works once, and the ±1 step drift window allows for clock skew. There are 10 recovery codes, stored hashed and each usable once.
      - Sign-in answers `mfa_required` when 2FA is on. It answers `mfa_setup_required` when enrolment is needed: always for super admins, and for staff whose tenant has `security.require_staff_2fa` on (checked at the handoff exchange for the generic domain). Challenges are bound to the host that started the login, and 5 wrong codes kill a challenge.
      - Account security endpoints: `mfa/setup|confirm|disable|recovery-codes`. Disabling is refused for super admins and under the tenant policy.
      - Passwords: `password/forgot` (always 202; 3 per email per hour; the link goes to the admin host for super admins and to the generic domain for staff, made by the Celery task at send time), `password/reset` (unlocks the account, ends every session, one use), `password/change` (ends other sessions, keeps this one). All are audited.
      - Frontend route for the reset link: `/reset-password/[uid]/[token]` (PLAN §7.1 listed `[token]` only).
    - Retailer sign-in (ADR-015):
      - `retailer/otp/request` always answers 202 with the same body; a code is sent only for an active retailer of that subdomain's tenant (or of any active tenant on the generic domain). `retailer/otp/verify` fails for an unknown number exactly like a wrong code.
      - Codes are 6 digits, hashed, valid 5 minutes, used once, and burn after 5 wrong tries. Limits: 3 per phone per 10 minutes and 100 per IP per hour.
      - On the generic domain there is a handoff (one account) or `choose_account` (several), showing only that phone's active accounts. `OTPRequest` has RLS (tenant rows plus tenant-less generic rows).
      - SMS goes through an adapter with a mock only (fixed `123456` in dev), sent by a Celery task with short retries.
      - `retailers` app stub: `Retailer`, `RetailerUser`, `create_retailer()`. `User.tenant` is set for retailer logins only, unique by (tenant, phone).
    - Staff and invitations:
      - `staff/`, `staff/{id}/` (role change, deactivate or reactivate), `staff/invitations/` (list, create), `.../resend/` (new link), `.../revoke/`, `roles/`, `permissions/`. All need `staff.manage` (Owner only) and are marked `impersonation_blocked`.
      - Invitations are tenant-scoped (RLS) and expire in 7 days; the email link goes to the tenant subdomain.
      - `auth/invitations/preview/` and `accept/` take the token in the body, not the URL, so it never reaches access logs (a small change from PLAN §3.2). A new person sets a name and password; someone with an existing staff account confirms with its password. Both are then signed in (2FA policy applies).
      - When the Owner accepts an ONBOARDING tenant's invitation, the tenant becomes ACTIVE (ADR-030).
      - Owner rules (ADR-030): the last active owner can't be demoted or deactivated, and nobody can deactivate themselves.
      - The plan staff limit counts active members plus pending invitations, and applies only when enforcement is on.
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

## Pre-production verification
Every `TODO(verify)` in the code is listed here, so each item is checked before launch. Search the code with `grep -rn "TODO(verify)" backend web/lib web/app web/components`.

| # | Item | Where | Verify against | Owner | Status |
|---|---|---|---|---|---|
| 1 | GST state code list: names and codes, and legacy codes 25 (Daman & Diu, pre-2020) and 28 (Andhra Pradesh, pre-2014) kept inactive | `backend/apps/platform/reference_data.py` (`STATES`) | GST portal state code list | Product owner | Open |
| 2 | GSTIN format for regular taxpayers (`[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]`) and the mod-36 check character. Other registration kinds (TDS/TCS, UN bodies, NRTP) are out of scope in v1 | `backend/apps/platform/validators.py`, `Tenant` check constraint `tenant_gstin_format` | GST portal / GSTN GSTIN format specification | Product owner | Open |
| 3 | Client IP and host behind proxies. The production load balancer must **append** the client IP to `X-Forwarded-For` and overwrite any client-supplied `X-Forwarded-Host`, and `TRUSTED_PROXY_HOPS` must match the number of appending proxies (1 with a load balancer in front of Next.js). Next.js itself only sets these headers when they are absent. Per-IP rate limits (ADR-030) and audit IPs depend on this | `backend/config/settings/base.py`, `backend/common/net.py`, infra (Phase 10) | Deployment topology and load-balancer documentation | Lead engineer | Open (before staging) |
| 4 | SMS provider for retailer OTP: implement a real adapter against the provider's official API, with a DLT-registered sender ID and OTP template (required in India). Only the mock exists; deployed environments refuse it (`check --deploy`: accounts.E001/E002) | `backend/apps/accounts/adapters/sms.py` | Chosen provider's API docs; TRAI DLT registration | Product owner (provider choice) + lead engineer | Open (before staging) |
| 5 | ADR-009 tax engine & rounding rules | `docs/DECISIONS.md` ADR-009 | Chartered accountant | Product owner | Open (before Phase 5) |

## Known issues / pending
- ADR-009 (tax engine & rounding) is pending CA confirmation, needed before Phase 5.
- Production domain to be supplied before staging (ADR-019).
- Next.js dev-server redirects built from `request.url` use the dev server's own host when the Host header is forged (curl). Real browsers are unaffected. Revisit if a reverse proxy sits in front in dev.
