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
- **Phase 1 — Tenancy, auth, platform admin** (branch `phase-1`, draft PR #2; plan approved 2026-09-25, including the wider PLAN §8 scope). **Merged to main (PR #2, 2026-09-25).**
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
    - Onboarding and platform APIs (`/api/v1/platform/`, `platform.*` permissions, admin host only):
      - Onboarding: `tenants/` POST in one transaction: tenant (ONBOARDING, GSTIN/PAN/state checked), profile, branding, Beta subscription and the Owner invitation email, audited in the tenant's log.
      - Tenant endpoints: list (status/search), detail (usage, owner, flags), edit (a slug change needs `confirm_slug_change`), suspend (reason required; takes effect at once), reactivate (ACTIVE, or ONBOARDING if no owner yet), per-tenant flags, subscription, users, owner resend-invite while ONBOARDING, slug-available, dashboard counts.
      - Masters: `plans/` (default switch), `feature-flags/` (a default change reaches every tenant), `tax-rates/` (rate immutable; activate/deactivate), `cess-types/`, `hsn-rate-hints/` (+ all-or-nothing CSV import).
      - Platform settings `settings/registry|values/`, the all-tenant `audit-logs/`, and public `public/states/`.
      - Cross-tenant reads go through `platform_db()`. The default warehouse stub stays in Phase 3 (not needed before inventory).
    - Tenant settings and branding:
      - Storage adapter (ADR-027): S3 via boto3 (SeaweedFS in dev) or in-memory (tests). Uploads go to the internal endpoint; download links are signed for `S3_PUBLIC_ENDPOINT_URL`. Keys are prefixed by tenant, and replaced files are deleted by a Celery task.
      - Image uploads: PNG/JPEG/WebP judged by content (Pillow), at most 2 MB and 4096 px; SVG refused.
      - Endpoints:
        - `settings/business/`: any staff reads, `settings.manage` changes; the slug is read-only.
        - `settings/bank-details/`: account number encrypted and masked, masked in the audit log, `impersonation_blocked`.
        - `settings/registry/` and `values/`: per-key edit permission, plus reset.
        - `settings/branding/` and `branding/assets/{logo|favicon|app_icon|signatory}/`.
        - `settings/signatory-image/`: private, via a presigned redirect.
        - `settings/features/`: tenant-toggleable flags only.
        - `audit-logs/`: `audit.view`, own tenant only.
        - Public `public/tenants/{slug}/branding/` and `.../assets/{kind}/` (a stable URL that 302s to a presigned link; never the signatory).
      - Checked against the running stack: logo upload to SeaweedFS and download through the public redirect.
    - Impersonation (ADR-029):
      - `platform/impersonations/` POST (reason, target staff or retailer of that tenant, never a super admin) returns a handoff code for the tenant subdomain. The token has no refresh and expires with the session (30 min, a platform setting).
      - Every request checks that the session is open. READ-ONLY refuses writes (`IMPERSONATION_READ_ONLY`). `auth/impersonation/act/` needs a reason. Endpoints marked `impersonation_blocked` refuse writes in every mode (`IMPERSONATION_BLOCKED`): staff management, 2FA, password change and bank details. A test fails if a route in those groups is unmarked.
      - Every successful write in a session is audited (`impersonation.write`), in addition to the domain entry that records the impersonator. Start, ACT, end and expiry go to the tenant's own log (the owner sees them); a beat task records expiries. Support can open a suspended tenant (ADR-018).
    - Django admin (PLAN 1.13): super admins only, admin host only; sign-in needs password + TOTP and uses the same lockout and rate limits. Read-only, through the platform alias. Third-party editable registrations (groups, token blacklist) removed; password, TOTP secret and webhook token never shown.
    - Role matrix (PLAN 1.17): a generic test walks every permission-guarded tenant endpoint and checks each system role gets 403 exactly when it lacks the code.
    - Checkpoint changes (ADR-032):
      - Neutral `TENANT_UNAVAILABLE` for every non-active tenant; public branding returns only `available`.
      - Forgot-password limit is a platform setting.
      - The web server (`web/server.mjs`) sets forwarded headers itself; Django trusts them only from `TRUSTED_PROXIES`; uvicorn proxy headers are off.
      - Checked live: 30 attempts with spoofed `X-Forwarded-For`, through Next.js and directly to Django, share one per-IP bucket (the 31st is 429). HMR still works through the custom server.
    - Frontend: sign-in (commit 13).
      - The access token is held in memory only. Refresh is single-flight and serialised across tabs (Web Locks); the fetcher retries once after a refresh on 401; the session is restored from the refresh cookie on reload.
      - `/login` adapts to the host: admin host, branded tenant subdomain (or the neutral unavailable message), or the generic domain with Shop owner / Staff tabs.
      - Steps: 2FA code or recovery code, enrolment with a QR code, recovery codes that must be confirmed as saved, tenant and distributor choosers, and handoff to the subdomain through the URL fragment (`/auth/handoff`).
      - Also `/shop/login` (phone, code, resend timer), forgot/reset password, `/invite/[token]`, and area guards, an account menu and a support-session banner in the shells.
      - Tenant branding (colour, name, favicon) is applied on the server in the root layout.
      - Orval now generates mutations for writes. `qrcode` added (web image rebuilt).
      - Checked live: super admin sign-in with 2FA enrolment and recovery codes, reload keeps the session, 2FA verify on the next sign-in, branded tenant login.
    - Frontend: super admin area (commit 14).
      - Dashboard (tenant counts), distributor list (search, status filter, cursor pages) and a six-step onboarding wizard (state filled from the GSTIN, live web-address check, one create call at the end).
      - Distributor detail: edit (web-address change needs an explicit confirmation), suspend with a reason, reactivate, resend the owner invitation while onboarding, modules, plan, users with "Support session" (reason → handoff to the subdomain in a new tab), and the tenant's audit log.
      - Plans, feature flags, GST rates / cess types / HSN hints (with CSV import that lists every rejected row), platform settings from the registry, the audit log across tenants, and support sessions.
      - "My account" (shared with /manage later): profile, password change (this session continues with new tokens), 2FA set-up, new recovery codes and turn-off (hidden when 2FA is required); password and 2FA hidden during a support session.
      - Shared: `FieldsDialog`, `ReasonDialog`, `KpiCard`, `AuditTable` with a before/after viewer, `RegistrySettingsForm`, `useCursor`. `ConfirmDialog` now shows failures and stays open.
      - Tests render with a strict i18n provider (a missing message fails the test) and a query client; `tests/mock-api.ts` stubs the API by method and path.
      - Checked live on desktop and at 360px (no horizontal scroll; the phone header now truncates the title and account name).
    - Seed (dev only, refuses without DEBUG): `<role>@<slug>.example.com` for OWNER, MANAGER, SALES, WAREHOUSE and ACCOUNTS in both demo tenants (password `staff-dev-password`); one shop each (98765 00001 / 00002) and a shop number registered with both (98765 00000) for the sign-in chooser. The super admin gets a fixed dev 2FA key when it has none, so E2E can sign in; an existing key is kept.
    - Frontend: distributor settings (commit 15).
      - Settings layout with its own section list (side list on wide screens, chips on phones), filtered by permission.
      - Business details (read-only unless `settings.manage`), invoice terms/footer/signatory with signature image upload; bank details for owners only and never during a support session; only changed fields are sent and the account number only when typed.
      - Branding: name and colour with a live preview of the shop sign-in (buttons, badges, link), logo / favicon / app icon upload and removal. A saved colour applies at once in the current tab; the server copy is cached for a minute.
      - Policies: one page per registry group (tax, invoicing, orders, stock, credit & payments, security) built from the settings registry, with reset to default; Modules page (only the ones the platform lets tenants switch).
      - Schema fix: asset delete and setting reset return 200 with a body (they were documented as 204).
    - Frontend: staff, roles, audit and accounts (commit 16).
      - Staff: list with inline role change, 2FA status, last sign-in, deactivate/reactivate after confirmation (never yourself; the last-owner rule is the server's); invite with a role (server field errors inline); invitations with resend and cancel.
      - Roles: read-only matrix of every tenant permission (grouped by area) against every role.
      - `/manage/audit` (owners): the tenant's audit log, support sessions included; record ids are shown as the kind of record, never raw ids.
      - `/manage/account` and `/shop/account` reuse "My account"; shop owners get profile and sign-out only.
      - `DataTable` now calls cell templates as functions instead of mounting them as components, so inline column definitions no longer remount cells (and in-cell controls keep focus and state) on every render.
    - Seed, E2E and docs (commit 17).
      - Acceptance E2E (`web/e2e/acceptance.spec.ts`, `make e2e-stack`, CI job `e2e-stack` on the docker compose stack): super admin signs in with 2FA and creates a distributor through the wizard → the owner's invitation is read from Mailpit → owner accepts on the tenant subdomain → sets branding (colour applies at once) → invites staff (email checked) → the tenant sign-in page shows the new name and the owner signs in. Shop owners: OTP sign-in on a subdomain, and on the main address choosing between two distributors (360px).
      - Bug found by the E2E and fixed: creating, editing, suspending or reactivating a tenant read the response through the platform connection before the request committed, so a new tenant came back "not found" (and the request rolled back) and edits came back unchanged. Those views now commit first (`CommitThenReadView`). Unit tests could not catch it because test settings mirror the platform alias onto the default connection; a structural test now guards the four views.
      - Public branding is no longer cached by the web server (it was for 60 s): a tenant activated by its owner no longer looks unavailable for a minute, and branding changes show on the next page load.
      - `seed --reset-admin-2fa` puts the dev super admin back on the dev 2FA key (`DEVSEEDADMINTOTPKEYDEVSEEDADMIN2`, dev only). Local dev admin was reset to it.
    - End-of-phase review follow-ups (ADR-033):
      - Public branding is cached per tenant in Redis again and invalidated on commit by branding, brand images, business name, web address and status changes; tests prove each change shows on the very next request. Brand image URLs are versioned.
      - The dev 2FA key is refused whenever DEBUG is off. The production image now runs `check --deploy --database default` before starting (accounts.E003 dev key present, accounts.E004 undecryptable 2FA secrets) and sets `DJANGO_SETTINGS_MODULE=config.settings.prod` (it fell back to dev settings before). Checked live: the prod container refuses to start against the dev database.
      - `reset_e2e_limits` (DEBUG only) is run by Playwright before each run and each sign-in step: `make e2e-stack` passed three times in a row.
      - Platform-alias audit: only the four tenant write views had the bug (fixed earlier). A static test now covers every view. The one other hit, 2FA set-up confirmation, was split into a sign-in path (commits before reading memberships) and an account-page path (never reads through the alias).
      - GSTIN: parameterised suite (78 cases) over the validator, onboarding, super admin edit and the distributor's business settings.
  - Deferred to later phases: invoice series (5), GST/gateway credentials (7), `ws-ticket` (4), platform dashboard KPIs (8), notification templates (6). Retailer is a stub until Phase 2.

## Next
- Phase 2 — Catalog, retailers, pricing (branch `phase-2`; plan approved 2026-09-25 with ADR-034 … ADR-036). Commits in order:
  0. Phase 1 decisions (state code 97 accepted, PAN holder types verified) and Phase 2 ADRs
  1. Catalog models
  2. `billing/tax.py` line math
  3. Catalog services and APIs (incl. effective-dated GST rates)
  4. Product images
  5. Product search
  6. Import framework + product import/export
  7. Retailers (+ import, welcome message)
  8. Price lists, special prices, discount rules
  9. `resolve_price`
  10. Shop catalog APIs — backend checkpoint
  11–15. Frontend (catalog, import wizard, retailers, pricing, shop + sign-out fix)
  16. Seed, E2E acceptance, docs
- Phase 2 done so far:
  - Commit 0: Phase 1 decisions (97 accepted, PAN holder types verified) and ADR-034 … ADR-036.
  - Commit 1: catalog models; search-vector triggers; append-only GST-rate history (cancellation only); default units per tenant.
  - Commit 2: `billing/tax.py` line and document math; PLAN §6.3 examples 1–10 and Hypothesis properties. The GST-inclusive one-paisa bound was also checked by brute force: 50,000 prices per rate.
  - Commit 3: catalog services and API: categories (3 levels), brands, units; products with barcodes, lookup and bulk actions; price-change audit; GST scheduling, cancellation and bulk scheduling. Isolation test on every route.
  - Commit 4: product images: background WebP variants on a public, unlisted bucket with immutable caching and content-versioned URLs. Checked live. `tenant_transaction()` keeps RLS working in non-atomic tasks, and a test runs the worker as `app_user`.
  - Commit 5: ranked search. On 20,000 products, as the runtime role, queries took 44–60 ms (target < 200 ms).
  - Commit 6: import framework and product import/export: dry run, change preview, xlsx error report, templates, round-trip export, messy-file handling (ADR-035). 21 import tests. Checked live through the worker.
  - Commit 7: retailers.
    - Full profile on top of the Phase 1 stub: code R-00001, GSTIN with the ADR-033 rules, state, addresses, credit limit and terms (credit permission, audited), hold/unhold, salesperson, tags and language. The migration renames the stub's fields and backfills codes and states; checked on dev data.
    - Soft delete ends the sign-in; a re-added number takes the login over. Changing the mobile moves the sign-in.
    - Sales staff can be limited to their own shops (`orders.sales_visibility`).
    - Shops on hold: new setting `retailers.blocked_can_sign_in` (default on). When it is off, sign-in, hand-off and every request say "Your account is on hold. Please contact your distributor." (`RETAILER_ON_HOLD`); the code is still sent, so the request looks the same for every number. `/auth/me` reports `on_hold` for the shop's notice.
    - Welcome message through the SMS adapter (mock; DLT template on the pre-production list).
    - Retailer import and export (matched by mobile; the number and sign-in never change on update; credit columns need the credit permission).
  - Commit 8: price lists (deletion refused while shops or rules use one; shop counts), bulk price upsert (one audit entry with old → new per product code), retailer special prices (audited; sales staff limited to their shops), discount rules with quantity slabs and validity dates. Rules are validated in plain words (targets exist in this tenant, percentage ≤ 100, slabs unique) and backed by check constraints. Price lists can be assigned per shop, in bulk or by import.

## Pre-production verification
Every `TODO(verify)` in the code is listed here, so each item is checked before launch. Search the code with `grep -rn "TODO(verify)" backend web/server.mjs web/server web/lib web/app web/components`.

| # | Item | Where | Verify against | Owner | Status |
|---|---|---|---|---|---|
| 1 | GST state code list: names and codes, and legacy codes 25 (Daman & Diu, pre-2020) and 28 (Andhra Pradesh, pre-2014) kept inactive | `backend/apps/platform/reference_data.py` (`STATES`) | GST portal state code list | Product owner | Open |
| 2 | GSTIN format for regular taxpayers (`[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]`) and the mod-36 check character. Other registration kinds (TDS/TCS, UN bodies, NRTP) are out of scope in v1 | `backend/apps/platform/validators.py`, `Tenant` check constraint `tenant_gstin_format` | GST portal / GSTN GSTIN format specification | Product owner | Open |
| 3 | Production load balancer configuration. It must append the client IP to `X-Forwarded-For` and set `X-Forwarded-Proto`. The web server's `TRUSTED_PROXIES` must list the load balancer's addresses, and Django's `TRUSTED_PROXIES` must list the web servers' addresses (ADR-032; our own code already discards client-supplied forwarded headers) | infra (Phase 10), `web/server.mjs`, `backend/config/settings/base.py` | Load balancer documentation and the deployment topology | Lead engineer | Open (before staging) |
| 4 | SMS provider for retailer OTP and the welcome message: implement a real adapter against the provider's official API, with a DLT-registered sender ID and OTP template (required in India). Only the mock exists; deployed environments refuse it (`check --deploy`: accounts.E001/E002) | `backend/apps/accounts/adapters/sms.py` | Chosen provider's API docs; TRAI DLT registration | Product owner (provider choice) + lead engineer | Open (before staging) |
| 5 | ADR-009 tax engine & rounding rules | `docs/DECISIONS.md` ADR-009 | Chartered accountant | Product owner | Open (before Phase 5) |
| 6 | GST Unit Quantity Codes (UQC) of the default units (PCS, NOS, BOX, CTN, PAC, DOZ, BTL, SET, KGS, GMS, LTR, MLT, MTR) | `backend/apps/catalog/defaults.py` | GST portal UQC list | Product owner | Open (before Phase 7) |
| 7 | Production public bucket and CDN for product images: anonymous `GetObject` only (no `ListBucket`), `Cache-Control` passed through, `PUBLIC_ASSETS_BASE_URL` set to the CDN (ADR-034) | `backend/common/storage.py`, infra (Phase 10) | AWS S3 / CloudFront documentation | Lead engineer | Open (before staging) |

## Known issues / pending
- ADR-009 (tax engine & rounding) is pending CA confirmation, needed before Phase 5.
- Production domain to be supplied before staging (ADR-019).
- Signing out from `/shop/account` lands on `/shop/login?next=/shop/account`, so the next sign-in returns to the account page instead of home. Harmless; tidy up in Phase 2 with the shop home.
- Next.js dev-server redirects built from `request.url` use the dev server's own host when the Host header is forged (curl). Real browsers are unaffected. Revisit if a reverse proxy sits in front in dev.
