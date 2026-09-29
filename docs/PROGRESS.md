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
- **Phase 5 — Billing, GST, ledger, credit control** (branch `phase-5` from `main` ac84f63; plan approved 2026-09-28 with ADR-046, PLAN §10.2g, SPEC 1.5). Commits in order:
  1. Docs: ADR-046, PLAN (§10.2g, return dispositions, salesman collections, ageing basis, backlog), SPEC 1.5, `docs/CA_REVIEW.md` first draft — **done**
  2. Tax engine: amount in words, HSN summary, FY helpers, credit-note proration; §6.3 examples, exhaustive matrix, property tests — **done** (`apps/billing/tax.py`):
     - Amount in words in the Indian system (lakh, crore, paise); HSN-wise summary summed from the lines; financial year of an IST date ("2026-27", "26-27" in numbers); due date = invoice date + terms.
     - Credit notes (§6.5): a partial return takes the same share of the line's taxable value, taxes at the invoice line's rates; the return that uses up a line takes exactly what is left; the credit note that uses up the invoice takes the invoice total minus earlier credit notes, so the balance lands on zero. A share worth less than a paisa credits nothing until the last return (found by Hypothesis).
     - Tests: the §6.3 examples (Ex 11 comes with invoice issuing), the §6.4 matrix (8 rates × 2 supply types × 4 discounts × 4 quantities × 4 prices under all 16 setting combinations, checking every invoice invariant), a guard that the matrix covers every allowed setting value, words for 0 to 100 crore, FY boundaries in IST, and a property test that returns in any number of parts reverse a line exactly.
  3. Models: billing, ledger, payments; RLS, checks, append-only and immutability triggers; `OrderLine.qty_invoiced` — **done**:
     - Billing: `DocumentSeries` (invoices, credit notes, receipts; prefix 1–3 characters so numbers fit in 16), `Invoice` (one per shipment; seller/buyer snapshots, supply type, settings snapshot, totals, running paid/credited/balance with a check that they add up, PDF and e-invoice columns), `InvoiceLine`, `CreditNote` (kind, return reason, issued automatically, applied to the invoice vs credit left), `CreditNoteLine` (per-line disposition), `OrderConfirmation`.
     - Ledger: `RetailerAccount` gains totals and unapplied credit (balance checked against the totals), `LedgerEntry` (append-only, one side only, posted once per reference), `LedgerAdjustment` (opening balances and manual debits/credits; debits are owed and age like invoices), `Allocation` (one source: payment, credit note or credit adjustment; one target: invoice or debit adjustment; append-only, reversals are negative rows). It replaces the planned payment-only allocation so advances and credit-note credit are matched the same way (PLAN §2.11).
     - Payments: `Payment` with modes, statuses, cheque credit timing snapshot, handover status for salesman collections, unapplied amount, receipt PDF.
     - Database guards: tenant isolation on every new table; a new `MakeImmutableExcept` trigger lets issued invoices and credit notes change only their running, PDF and e-invoice columns and refuses deletes; lines, ledger entries and allocations are append-only. `OrderLine.qty_invoiced` (checked within ordered minus cancelled).
  4. Numbering service (gapless, FY in IST, ≤ 16 characters) with a race test — **done** (`apps/billing/numbering.py`): `INV/26-27/000001`, `CN/…`, `RCT/…`; the number is taken under the series row lock inside the issuing transaction (lock level L6, last), so a failed issue leaves no gap; each financial year restarts at 1 and inherits the latest prefix; a prefix change (1–3 capital letters or digits, audited) applies from the next number. The platform default prefix now allows 1–3 characters (was 6, which could not fit 16). Race test: 12 documents at the same moment get 12 numbers in a row; removing the lock fails it.
  5. Ledger posting, opening balances (adjustment + import), adjustments — **done** (`apps/ledger/services.py`, `allocation.py`):
     - `post`: one append-only entry on a locked account, with the balance after it; account totals kept in step (the database checks balance = debits − credits).
     - Allocation engine: sources (payments, credit-note credit, credit adjustments) meet targets (invoices, debit adjustments), oldest money against the earliest due; manual allocation and reversal (a negative row; the money is free again). Allocations never change the balance.
     - Adjustments (audited): an opening balance once per shop (owed or advance), debit and credit adjustments with a narration. A debit is owed and ages (opening dues are due at once, others after the shop's terms); a credit is used like an advance, straight away for anything owed.
     - Opening balances import (`OPENING_BALANCES`, `ledger.adjust`): shop by mobile or code, amount owed (minus for an advance), as-of date, note; one per shop, errors per row.
     - `check_ledger` test helper: every shop's balance equals its entries, the last entry, invoices − payments − credit notes ± adjustments, and what is owed minus unused credit; every invoice and source agrees with its allocations. The shop's account lock (L1) moved to the ledger app.
  6. Invoice issuing for both timings, invoice-date rates and warning, snapshots, advances applied; the Phase 4 dev command — **done** (`apps/billing/invoicing.py`):
     - One invoice per shipment, idempotent. At dispatch (default) for the packed quantity; with ⚙ `invoicing.timing` = ON_ACCEPTANCE, at acceptance for shipment 1 and when a backorder shipment is confirmed (trigger ON_ALLOCATION); dispatch then issues nothing more. The order's snapshot decides the timing.
     - Tax at the rate valid on the invoice date; each line keeps the order's rate and is flagged when they differ (Ex 11). Prices are read with the order's inclusive/exclusive basis; rounding follows the settings in force now and is saved on the invoice. Discounts are the order line's in proportion, or for a repriced backorder shipment the discount at today's price (saved on the shipment line).
     - Seller snapshot (GSTIN, address, bank, terms, footer, signatory) and buyer snapshot (shop, GSTIN, addresses); place of supply and CGST+SGST / IGST from the order.
     - The ledger is debited, `OrderLine.qty_invoiced` goes up, and advances or unused credit are applied at once (oldest money first). Outbox `invoice.issued`.
     - Phase 4 shipments dispatched without an invoice: `manage.py invoice_phase4_shipments` (DEBUG only; `make seed` runs it) invoices them today with trigger AFTER_DISPATCH.
  7. Credit notes: returns with dispositions, value adjustments, automatic short-supply / cancellation, exact remainders — **done** (`apps/billing/credit_notes.py`):
     - Returns (`invoices.manage`): per line a quantity and what happened to the goods: back to stock (RETURN movement, then waiting backorders are served, trigger RETURN), received damaged (RETURN then DAMAGE), or not physically returned (value only). A reason per note (damaged, expired, wrong item, excess supply, other with a note).
     - Price adjustments: a taxable amount per line with a required reason, taxed at the invoice line's rates.
     - Exact remainders: the return that uses up a line takes what is left, and the note that uses up the invoice lands its balance on zero (3 + 7 of 10 at ₹123.45: ₹389 + ₹907 = ₹1,296).
     - Posting: ledger credit; applied to its own invoice up to what is owed there; the rest is credit for the shop's next dues (applied straight away, oldest first).
     - Automatic notes ("Issued automatically"): with ON_ACCEPTANCE invoicing, a short pack (SHORT_SUPPLY), a cancelled shipment, a cancelled accepted order and a declined repriced backorder (CANCELLATION) credit what was invoiced but not supplied; `qty_invoiced` goes down first, so the quantity can be invoiced again when it ships later. Outbox `credit_note.issued` carries `issued_automatically` for Phase 6.
     - Lock order: account (L1), stock levels (L3) before the invoice (L5) and the number series (L6). Fixed the credit-note check constraint (`billing/0002`): credit not yet used is at most the note's total.
     - Tests: 12 (returns in parts, each disposition's stock movements, backorder served by a return, validation, price adjustment, credit beyond the invoice paying the next one, every automatic path with ledger and order invariants). Removing the `qty_invoiced` decrement fails 5 of them.
  8. Payments: offline modes, FIFO/manual allocation, advances, cheques, reversals, salesman collections and handover; reconciliation property test — **done** (`apps/payments/services.py`, `selectors.py`):
     - Recording (`payments.record`): cash, bank transfer and UPI are credited at once; a cheque follows ⚙ `payments.cheque_credit_timing`, saved on the payment (credited when received, or waiting for clearance with no ledger effect). A receipt number `RCT/26-27/000001` either way. Outbox `payment.received`.
     - Matching: the dues the user chose first, then anything else owed, the earliest due first; the rest is the shop's credit. With ⚙ `payments.hold_advances` off, more than the shop owes is refused (`PAYMENT_EXCEEDS_OUTSTANDING`, with the amount owed).
     - Cheques: clear (credited then, if it was waiting), bounce (a credited cheque is reversed automatically). A payment entered in error is reversed (`payments.reverse`, reason required). Either way its allocations are undone, a `PAYMENT_REVERSAL` debit points at the original entry, and the shop's other credit then covers what it can. Audited, outbox `payment.reversed`.
     - Salesman collections: new permission `payments.collect` (Sales only; the office uses `payments.record`), shops the salesman can see, ⚙ `payments.sales_can_collect` (default on). Credited at once, "With salesman" until a `payments.record` user confirms "Handed over" (in bulk, audited per payment). Pending-handover report per salesman (count, amount, oldest date) and a total for the dashboard.
     - Reallocation: undo any allocation (automatic or by hand), optionally moving the money to other dues in the same step; allocate unused money by hand. Audited.
     - New settings `payments.sales_can_collect` and `receivables.ageing_basis` (used in item 9), with labels.
     - Tests: 15 payment tests, plus the reconciliation property test. It runs random sequences of shipments, payments in every mode, cheque clears and bounces, reversals, returns, adjustments and reallocations under every combination of `hold_advances` × `cheque_credit_timing`, and checks the ledger after every step (60 examples; every kind of step both succeeds and is refused somewhere). Planted bugs (a reversal leaving the unused credit, a payment not matched) fail it.
  9. Credit control: real exposure, overdue blocking, holds; outstanding, overdue, ageing — **done** (`apps/orders/credit.py`, `apps/ledger/selectors.py`):
     - Exposure (ADR-013) = ledger balance + cheques credited on receipt that haven't cleared + the value of open order quantities not yet invoiced (ordered − cancelled − invoiced) + this order. Invoicing moves value from the orders to the ledger, so exposure doesn't jump at dispatch or acceptance (only the rupee rounding changes).
     - Overdue blocking (⚙ `credit.block_overdue_after_days` = N): anything owed more than N days past its due date (invoices, opening balances, debit adjustments) counts as a breach, whatever the limit. The same hold or block as over-limit, with hold reason OVERDUE, the new error and cart problem `OVERDUE_INVOICES`, and "you have overdue bills" wording in the shop and staff carts (the cart's credit block now says why). Backorder allocation skips and flags the shop; an order approved from a hold is still covered.
     - Receivables: open dues (the earliest due first); ageing per shop in buckets 0–30 / 31–60 / 61–90 / 90+ by invoice date (default) or days past due (⚙ `receivables.ageing_basis`, with "Not due"), owed, overdue, unused credit, net; one shop's outstanding (owed, overdue, days overdue of the oldest); dashboard summary (owed, overdue, shops overdue, due in the next 7 days, unused credit).
     - Tests: 11 (exposure through invoice, payment and cheque clearance; acceptance invoicing; overdue boundary (N days is fine, N+1 is not), hold reason, block, lifting by payment or setting; backorder skip and approved-hold cover; ageing on both bases; outstanding and summary), and a cart test for the overdue wording.
  10. PDFs: invoice (three copies for staff), credit note, receipt, Order Confirmation; background rendering, storage, signed links; CA sample PDFs — **done** (`apps/billing/documents.py`, `pdf.py`, `tasks.py`, `templates/billing/`):
     - Renderer adapter: WeasyPrint (Pango and Noto Sans, which has ₹, are now in the backend image and the CI backend job), or a fake that carries the HTML (tests; refused unless mocks are allowed). WeasyPrint is imported only when rendering.
     - Documents on A4: tax invoice (seller and buyer, place of supply, supply type, reverse charge, lines with HSN, qty, rate, gross, discount, taxable value, CGST/SGST or IGST with rates, cess when any; totals, round-off, amount in words, HSN summary, rate-change note, bank details and terms, signatory; IRN/QR block only once an IRN exists). The shop's original, and one PDF of three labelled copies for staff. Credit note (the invoice it corrects, reason, what happened to returned goods, "Issued automatically"), payment receipt (what it paid, credit kept, "subject to the cheque being cleared"), Order Confirmation ("This is not a tax invoice.", a snapshot made at acceptance when ⚙ `orders.send_confirmation_on_accept` is on). Delivery address only when it differs from billing.
     - Background: the outbox events (`invoice.issued`, `credit_note.issued`, `payment.received`, `order_confirmation.created`) queue `billing.render_document`. It builds the HTML in a short transaction, renders and stores it with none held, then records the key. Retried with backoff; after the last try the status is FAILED (regeneration comes with the APIs). Private keys under `tenants/<id>/documents/…`, downloaded by 5-minute signed links.
     - CA samples: `docs/ca/sample-invoice.pdf`, `sample-invoice-copies.pdf` and `sample-credit-note.pdf` from CA_REVIEW Example 5 and CN 1 (₹8,892.00 with +₹0.01; ₹437.00 with −₹0.01), printed by `manage.py render_ca_samples` (in the backend container; no database writes).
     - Tests: 11 (Indian grouping, the original vs three copies, IGST layout, credit note and receipt contents, the automatic label, the confirmation on/off, retry then FAILED, fake renderer refused in production, the CA samples) plus a real WeasyPrint test, which runs in CI and the container and skips on machines without Pango.
     - Dev note: `make up` rebuilds the backend image with the PDF libraries. Host-run code on macOS can't render (no Pango) unless `PDF_RENDERER=fake`.
  11. APIs (staff, shop), GST identity lock (5.13), isolation and role tests, demo billing, API client — **done; backend checkpoint**:
     - Billing (`invoices.view` / `invoices.manage`): `invoices` (filters: shop, payment status, overdue, dates, e-invoice status, search), `invoices/{id}` (lines with the quantity already credited, credit notes, money applied), `invoices/{id}/pdf` (`?copies=true` for the three copies; 202 while it is being prepared), `invoices/{id}/regenerate-pdf`; `credit-notes` (list; create a return or a price adjustment with an Idempotency-Key), `credit-notes/{id}` (where its credit went), `/pdf`, `/regenerate-pdf`; `orders/{id}/confirmation` (`orders.view`).
     - Receivables (`ledger.view`): `receivables` and `receivables/ageing` (per shop: buckets, owed, overdue, unused credit, net, oldest due, last payment, credit limit, salesperson; totals; search, salesperson, overdue-only; `?basis=` overrides the setting), `receivables/summary` (dashboard: owed, overdue, shops overdue, due this week, unused credit, and collections with salesmen for `payments.record` users), `retailers/{id}/ledger` (statement with opening, running and closing balance; default last 90 days, at most two years), `retailers/{id}/dues` (what is owed and unused money, for the payment form), `ledger/adjustments` (`ledger.adjust`, Idempotency-Key).
     - Payments: `payments` (list with filters; record with chosen dues, Idempotency-Key; `payments.record`), `payments/{id}` (where the money went), `/allocate`, `/clear` (`payments.record`), `/bounce`, `/reverse` (`payments.reverse`), `/receipt`, `/regenerate-receipt`; `payments/collect` (`payments.collect`, Idempotency-Key), `payments/handover` (bulk), `reports/collections-pending-handover`, `payment-allocations/{id}/reverse` (undo and optionally reallocate).
     - Shop: `shop/invoices` (unpaid, paid, overdue), `shop/invoices/{id}`, `/pdf` (the original only), `shop/credit-notes/{id}/pdf`, `shop/ledger`, `shop/account` (position, credit limit and available credit, ageing, overdue bills, whether orders are held for overdue bills), `shop/payments`, `shop/payments/{id}`, `/receipt`, `shop/orders/{id}/confirmation`; `shop/home` gains the outstanding and overdue amounts.
     - GST identity lock (task 5.13): after the first invoice, GSTIN, legal name and state are read-only for the distributor and in the super admin's normal edit (`GST_IDENTITY_LOCKED`); both screens get `gst_identity_locked`. The super admin changes them with `platform/tenants/{id}/gst-identity` (reason required, audited `tenant.gst_identity_changed`); issued invoices keep their snapshot.
     - Sales staff limited to their own shops see only those shops' invoices, credit notes, payments, receivables and statements; other shops' are "not found".
     - Demo billing in `make seed`: opening balances (one 45 days overdue, one advance), a bank transfer paying an invoice, a UPI part payment, a cheque credited on receipt, a salesman's cash collection waiting for handover, and a return credit note. The worker prints every PDF.
     - Tests: 24 API tests (roles, visibility, idempotent replays, PDF links, filters) plus a cross-tenant test for every new route (38). The seed test checks the demo billing and reconciles the ledger. API client regenerated; the new enums have stable names.
  11b. Checkpoint rules (ADR-047) — **done**:
     - Old bills: an opening balance may be several unpaid old bills per shop, each with its bill date, a due date (the shop's terms after the bill date if empty) and an optional bill number (once per shop); they age and fall overdue like invoices. The import has columns shop, amount, bill number, bill date (required), due date, note. An opening advance stays once per shop.
     - Payment dates: the payment's own date is the ledger entry date, also for a cheque credited when it clears; payments dated in an earlier financial year than recorded are flagged (`dated_in_previous_financial_year`), and the dues response gives the financial year's start for the form's warning. CA question 21.
     - Credit kept although advances are off is shown on the payment and the shop's account.
     - Handover: a collection reversed as an error becomes "Nothing to hand over" and leaves the report; bouncing a cheque still with the salesman records its handover first (audited, naming the user).
     - Tests: 5 new (payment date, earlier year, advances-off notice, both handover rules) plus updated ledger, import and credit-control tests.
  11c. Refunds from a shop's credit — **done** (ADR-047 item 4):
     - `Refund` (own series `RFD/26-27/000001`): cash, bank transfer or UPI, dated (never in the future), never more than the shop's unused credit (`REFUND_EXCEEDS_CREDIT` with what is available). A REFUND ledger debit; the refund is a target in the allocation engine, covered at once by the shop's unused money, oldest first. If that money is undone later (a bounced cheque, a reversal), the refund is owed again: it shows in the shop's dues and receivables, counts for overdue blocking and is covered by the next money. The money used for a refund can't be moved by hand.
     - Audited (`payments.refund_recorded`), outbox `refund.recorded`, refund voucher PDF (paid to, amount in words, the credits it used, signatures).
     - API: `refunds` (list, record with an Idempotency-Key), `refunds/{id}` (the credit it used), `/voucher`, `/regenerate-voucher`; payments and credit notes show a refund they paid for.
     - Tests: 5 (oldest credit first and the voucher; the limit and validation; a bounced cheque making the refund owed; a refund after a return; API roles and isolation). The reconciliation property test gained a refund step (about 13% of examples pay one back, as many are refused); skipping the credit use fails it.
  12. Frontend: invoices and credit notes — **done**:
     - `/manage/invoices`: list (search, payment state, overdue only, dates; cards on phones) with what is still owed and days overdue.
     - `/manage/invoices/{id}`: lines (HSN, quantities, discount, taxable value, GST, "ordered at 12%" where the rate changed, quantity already credited), totals with paid, credited and still owed, credit notes, money applied (payments and credits, automatic or by hand), download PDF and "Print 3 copies", print again after a failure, "Credit note".
     - `/manage/invoices/credit-notes`: list (kind, issued automatically or by staff) with "Issued automatically (short supply / cancellation)"; detail with lines, what happened to returned goods, reason, where the credit went, PDF.
     - `/manage/invoices/credit-notes/new`: pick an invoice, then a return (quantity back and what happened to the goods per line, reason, note) or a price adjustment (taxable value per line, note); sent once per Idempotency-Key; the server works out every amount.
     - Order page: its invoices and the Order Confirmation download (the API now lists an order's invoices and whether a confirmation exists).
     - A shared document button opens a PDF's short-lived link, or says it is being prepared.
     - Tests: 5 component tests; the new screens are in `e2e/responsive.spec.ts` (`e2e_ids` gives an invoice and a credit note).
  13. Frontend: payments, refunds, handover, receivables and a shop's account — **done**:
     - `/manage/payments`: list (search, mode, status, handover, dates; "Earlier financial year" flag). "Record payment" (`payments.record`) or "Record collection" (sales staff with `payments.collect`).
     - `/manage/payments/new`: pick the shop (or `?retailer=`), see what it owes, overdue and credit (and the advances-off notice), amount, mode, date (a warning when it falls in an earlier financial year), cheque or reference fields; the office can choose bills to pay first (the rest goes to the oldest). Collections go to the collect endpoint without bill choices. Idempotency-Key per form; refusals (e.g. more than owed with advances off) in plain words.
     - `/manage/payments/{id}`: notices (earlier year, credit held with advances off), what it paid with "Move" (undo and reallocate with a reason), "Use the credit", "Cheque cleared" (with the date), "Cheque bounced", "Reverse", "Mark handed over", receipt download.
     - `/manage/payments/handover`: totals per salesman and bulk "Mark handed over".
     - `/manage/payments/refunds` (list, new with the shop's credit as the limit, detail with the credit it used and the voucher).
     - `/manage/receivables`: summary cards (owed, overdue shops, due this week, with salesmen), ageing by days since the bill or days past due, totals per bucket, search and overdue-only, pages.
     - `/manage/retailers/{id}/ledger`: the shop's position and credit limit, statement by dates with opening, running and closing balances linking to each document, "Record payment", "Refund credit", "Adjustment" (old bill with bill date, due date and number; opening advance; debit; credit). The shop page links to it.
     - Tests: 6 component tests (bills paid first and the earlier-year warning, collection mode, a refusal, payment notices and actions by permission, bulk handover, ageing basis). New screens in the responsive check; the seed adds a refund and `e2e_ids` a payment and a refund.
  14. Frontend: dashboard, credit holds and settings — **done**:
     - Dashboard: "Money to collect" cards (owed, overdue shops, due in the next 7 days, with salesmen or unused credit) linking to receivables and the handover page, for users who see receivables.
     - Orders on hold say why: over the credit limit, or overdue bills (staff and shop order pages).
     - Business settings: GSTIN, legal name and state are read-only after the first invoice, with a note; the super admin's tenant page has "Change GST identity" (with a reason) once it is locked, and the normal edit keeps those fields read-only.
     - Invoice settings: "Document numbers" shows each series' next number and how many were issued this year; those who manage settings change a prefix (from the next number). New API `settings/document-series` (any staff reads; `settings.manage` changes; audited; isolation test).
     - Tests: 6 component tests (numbering, dashboard money, GST lock in settings and on the platform page, overdue hold wording with the order's invoices and confirmation).
  15. Frontend: the shop's bills, statement, payments and account — **done**:
     - `/shop/account` is the account menu: what the shop owes and what is overdue, its credit with the distributor and how much it can still order, a notice when orders wait because of overdue bills; links to My bills, Statement, My payments and the profile (moved to `/shop/account/security`); Sign out.
     - `/shop/invoices` (To pay, Overdue, Paid; days late or pay-by date), `/shop/invoices/{id}` (still to pay, download the bill (the original), items with quantities returned, totals, credit notes to download), `/shop/statement` (dates, balance before and after, each entry with the balance), `/shop/payments` (amount, date, mode, who collected it, bounced or waiting to clear, receipt).
     - Home: "You owe ₹X · ₹Y overdue" (or "You have credit of") linking to the account; order page: its bills and the Order Confirmation download.
     - Tests: 3 component tests; the shop screens are in the responsive check.
  16. E2E acceptance (both invoice timings) and responsive check — **done** (`web/e2e/billing-acceptance.spec.ts`, in `make e2e-stack` and CI): a fresh distributor; at dispatch the invoice is issued for what was packed, printed by the worker (the PDF link is polled until ready), paid in full from the shop's account page with a receipt; one unit comes back on a credit note, kept as credit, and part of it is refunded with a voucher; the shop at 360 px sees its credit, the paid bill with "1 returned", the bill PDF, its statement (invoice, payment, credit note, refund) and the receipt. After switching invoicing to "when the order is accepted", the next order is invoiced at acceptance with its Order Confirmation, and cancelling it issues a credit note automatically (the invoice ends fully credited). The responsive sweep covers the 27 new screens; its first run found 40 px back links, overlapping header links on phones and a 13 px overflow on the statement at 768 px, all fixed.
  17. Final review — **approved (2026-09-28)**: the product owner's manual test passed on a laptop and a phone (the full list: dashboard, invoices and PDFs, credit notes, payments, cheques, allocations, collections and handover, refunds, receivables and ageing, statements, old bills, overdue blocking, advances off, invoicing at acceptance, number prefixes, GST lock, sales collections, the shop's bills, statement and payments), plus CGST/SGST and inter-state IGST checked by hand, the ledger balance against invoices, payments, credit notes and refunds, invoice immutability, gapless numbering for every series and the GST identity lock. Old bills confirmed as several per shop.
  18. Refund reversal (final review request) — **done**: `refunds/{id}/reverse` (`payments.record`, reason required, audited `payments.refund_reversed`): the money the refund used is back in the shop's credit and pays what it owes, oldest first; a REFUND_REVERSAL credit points at the original entry; status "Reversed"; the voucher is printed again marked "Reversed" (outbox `refund.reversed`). "Reverse (error)" on the refund page; statements show "Refund reversed". Tests: 4 backend (credit restored exactly and the voucher marked, restored credit paying a later bill, a refund owed again after a bounce cancelled, API roles and isolation), 2 component tests; the reconciliation property test gained a reversal step (about 11% of examples reverse a refund); leaving the refund owed after reversal fails it.
- **Phase 6 — Notifications** (branch `phase-6` from `main` cbd74ab; plan approved 2026-09-29 with ADR-048, PLAN §10.2h, SPEC 1.6). Commits in order:
  1. Docs: ADR-048, PLAN (§2.13 models, §3.11 endpoints, settings, §10.2h with the default rules table, Phase 6 tasks), SPEC 1.6 — **done**
  2. Models, event catalogue, default rules and English templates — **done** (`apps/notifications`):
     - Models: `PlatformTemplate` (super admin's defaults) and `NotificationTemplate` (tenant overrides), `NotificationRule` (tenant overrides of the rules in code), `Notification` (unique per event, recipient and channel; status, skip reason, quiet-hours hold, read, attempts, provider ids), `DeliveryAttempt`, `NotificationPreference`, `DocumentLink` (hashed token, expiry, revocation, opens), `ReminderPause` (one open per shop), `WhatsAppSender` (a distributor's own number later; encrypted credentials), `Announcement`. Row-level security on every tenant table. `Retailer` gains WhatsApp opt-in, time, source, opt-out time and the one-time prompt time.
     - Catalogue (`catalog.py`): 36 notification events (the outbox events, split where the default depends on context: placed for the shop, cancelled by the shop, dispatched after an earlier invoice, bounced cheque, waiting items cancelled by the shop), each with its group, urgency, WhatsApp category, variables and linked document; the default rules of PLAN §10.2h; English texts for in-app, email, WhatsApp and SMS, each WhatsApp/SMS text naming the distributor first. Platform templates are seeded by a migration (edits kept).
     - Tests: 5 consistency tests (rules vs events, channels, permissions; texts use only the event's variables; WhatsApp parameters in order; the approved compulsory, non-urgent and marketing sets; seeding).
  3. Event consumer: rule resolution, recipients, preferences, compulsory flags, WhatsApp consent, idempotent notifications — **done** (`consumer.py`, `context.py`, `rules.py`, `render.py`):
     - Every notifying outbox event queues `notifications.dispatch_event`, which picks the notification by context (placed by staff, cancelled by the shop, dispatched after an invoice issued at acceptance or allocation, bounced cheque, waiting items cancelled by the shop; `backorder.cancelled` now says who cancelled). Confirmation-created and alert-resolved events notify nobody.
     - Rules in force = the catalogue's defaults, overridden per event, recipient and permission by the tenant's rows (switched off, other channels, compulsory), plus recipients the tenant added.
     - Recipients: the shop's logins, the shop's salesperson, the salesman who collected, active staff whose role has a permission, owners. A person named by several rules gets one row per channel. A shop's WhatsApp, SMS and email go once to the shop's own number and address (through the login that signs in with it); every login gets in-app.
     - Rows that can't be sent are kept as "Not sent" with the reason: WhatsApp not enabled, no WhatsApp consent (compulsory events too), no address, switched off by the person (never for compulsory events, never in-app). In-app rows are delivered on creation; the rest wait for delivery (item 4).
     - Texts: the tenant's template, else the platform's, in the person's language then English; only `{{ variable }}` is replaced, nothing else is evaluated. Links go to the shop's or the staff page on the tenant's address; the linked document is recorded for item 5. The WhatsApp row carries the approved template name, category and parameters in order.
     - Idempotent: one row per event, person and channel; a redelivered event creates nothing.
     - Tests: 11 (office, salesperson and shop reached with the right links; redelivery; feature, consent then sent, distributor named first; compulsory invoice ignores preferences and emails the shop; switched-off and missing email; context splits; dispatch after an acceptance invoice; tenant rules; sandboxed tenant template; another tenant gets nothing). Planted bugs (no consent check, preferences overriding compulsory events, in-app switched off) fail them.
  4. Channel adapters (in-app with live badge, email mock/SES, WhatsApp mock/interface with per-tenant sender, SMS) and delivery with retries and the attempt log — **done** (`adapters/`, `delivery.py`, `checks.py`):
     - Email: `EMAIL_PROVIDER=django` (Mailpit in dev, in-memory in tests) or `ses` (SES v2 via boto3, TODO(verify) in the adapter). From "<distributor> <platform address>", reply-to the distributor's email.
     - WhatsApp: an approved-template interface (name, language, parameters in order, category) and a mock only (TODO(verify): provider, webhooks, one number for several businesses, STOP replies). The distributor's own number when it has an active `WhatsAppSender`, else the platform number (`WHATSAPP_PLATFORM_NUMBER`, `WHATSAPP_PLATFORM_NAME`).
     - SMS: the existing SMS adapter (mock until a DLT provider is chosen).
     - In-app: delivered on creation; everyone's socket now also joins `user.<tenant>.<user>`, and new rows ring those bells after commit.
     - Delivery: each external row is claimed (PENDING → SENDING, so it isn't sent twice), sent with no transaction held, and logged as a `DeliveryAttempt` (provider, response, error, duration). A failure is tried again after 1, 2, 4, 8 and 16 minutes, then "Failed"; a provider's "won't work" fails at once. A retry by hand gives a fresh round. `notifications.send_due` (every minute, per active tenant) sends retries, held messages, anything whose enqueue was lost (2 minutes) and rows left SENDING by a dead worker (10 minutes).
     - Deploy checks: `notifications.E001` (WhatsApp mock without the mock allowance), `notifications.E002` (email that would stay on the server).
     - Tests: 11 (email and WhatsApp to the shop with the attempt log; the distributor's own number; backoff then failed then retried by hand; permanent failure; the sweeper's stale and lost rows; no double send; SMS; deploy checks; bell groups; the bell over the socket for the right person and tenant only; bells after commit). Planted bugs (claiming a row being sent, never failing, a reset row not due) fail them.
  5. Sandboxed templates with tenant overrides and preview; secure document links — **done** (`links.py`, `texts.py`, `api/public.py`):
     - Document links: invoices, credit notes, receipts, refund vouchers and Order Confirmations. One link per event, made only when a shop's WhatsApp or email will carry it (never twice for a redelivered event). A 32-byte random token, only its SHA-256 stored, valid ⚙ `notifications.document_link_days` (default 30). `GET /api/v1/public/documents/{token}/` on the tenant's address (the tenant comes from the host) counts the open and redirects to a 5-minute link to the *current* PDF; otherwise a short page: "being prepared" (refreshes), "expired", "no longer works" (revoked), "doesn't work" (unknown, or another tenant's address). Throttled, `no-store`, `no-referrer`. Staff who manage the document (`invoices.manage`, `orders.manage`, `payments.record`) can revoke its links (audited `notifications.document_links_revoked`).
     - A reversed or bounced payment's receipt is now printed again (`payment.reversed` joins the PDF events), so the receipt link sent earlier shows "Cheque bounced" or "Cancelled".
     - Texts: a distributor overrides in-app and email texts per event and language (en, hi, mr), and can reset to the platform's; WhatsApp and SMS texts match provider-approved templates, so only the super admin edits them (with the approved name, language and category; parameters follow the text's order). Only the event's `{{ variables }}` are accepted (the error lists the allowed ones); `{% %}` is refused. Preview fills sample values. All audited (`notifications.template_changed`, `template_reset`, `platform_template_changed`).
     - Settings: new "Notifications" group with quiet hours (21:00–08:00), link days (30), payment reminder days (-2,3,7,15,30) and repeat (15), handover reminder days (2), edited with `settings.manage` like every setting; platform WhatsApp prices per category (rupees, up to 4 decimals, empty until set). Labels in the web app.
     - Tests: 9 (link carried by WhatsApp and email, hash only, redirect and opens counted; the days setting and no second link; no link when nothing carries it; expired, revoked with audit and permission, unknown, too long and another tenant's address; the receipt printed again after a bounce; own text used and reset; unknown variables, tags, WhatsApp channel, empty title, language refused; preview; the super admin's WhatsApp text).
  6. Quiet hours; payment reminders (cadence, pauses), handover reminders, GST rate-change warning — **done** (`quiet.py`, `jobs.py`, `tasks.py`):
     - Quiet hours: non-urgent events' WhatsApp, SMS and email rows get `send_after` = the end of the distributor's quiet hours (IST; windows may cross midnight; equal times turn them off) and are sent by `send_due` then. In-app and urgent events are never held.
     - Payment reminders (daily 10:00 IST): one message per shop listing the bills due within the "before" days or overdue ("2 bills to pay, ₹18,200.00 in all (₹12,000.00 overdue since 01-09-2026)" or "due on …"), on the configured days counted from the shop's oldest such bill, then every repeat days. The reminder texts were reworded to cover bills due soon (migration refreshes the platform texts). Compulsory for the shop; its salesperson gets it in-app. Staff pause a shop's reminders with a reason and an optional end date, or resume them (audited `notifications.reminders_paused` / `_resumed`); while paused, the rows are kept as "Not sent: paused" on every channel.
     - Handover reminders (daily 09:00 IST): one digest per salesman with collections older than the setting (count, amount, oldest), to the salesman (in-app, WhatsApp) and `payments.record` staff (in-app). Handing over now emits `payment.handed_over` (the salesman hears it in-app).
     - GST rate changes (daily 08:30 IST): products whose rate changes in exactly 7 days (not first rates, same rates or cancelled changes) in one message to `products.manage` staff (in-app, email); `upcoming_rate_changes` (next 30 days) feeds the dashboard card (API in item 8).
     - Every job is idempotent per day (ids derived from tenant, subject and date) and runs per active tenant from the beat.
     - Tests: 15 (8 quiet-hour cases; held reminder vs urgent invoice; reminder days incl. before-due, repeat and once a day; paid bills; pause, resume and a pause ending by itself; handover digest, handed-over message and none after; GST warning 7 days ahead). Planted bugs (no hold, pause ignored, daily repeat, bills outside the window) fail them.
  7. Consent capture (shop, staff, import), shop preferences, announcements — **done** (`consent.py`, `preferences.py`, `announcements.py`):
     - WhatsApp consent: recorded with its time and source: the shop in the app (the one-time prompt, remembered once shown, and a switch), staff (opting in requires "the shop agreed" to be confirmed), or the import's new "WhatsApp consent" column (Yes/No; also exported; "whatsapp" stays an alias of Mobile). Opting out is always allowed and turns WhatsApp messages still waiting (quiet hours, retries) into "Not sent: no WhatsApp consent". Audited (`retailers.whatsapp_opted_in` / `_opted_out`, with the source). The rules screen gets the opted-in count.
     - Preferences: everyone sees the messages their rules send them, per channel; in-app is locked on, and for a shop so are compulsory events' channels. Staff see the events their permissions, ownership, assigned shops or collections bring them.
     - Announcements: title, message, start and optional end, active flag, optional WhatsApp (marketing category, only to shops that agreed). Shown on shop homes while running; sent once to every active shop when they start (by the minute sweep). Audited.
     - The shop welcome SMS is now a notification (`retailer.welcome`: logged, retried, not switchable; the DLT template stays `retailer_welcome`); a resend is a new message. Invitation, password-reset and account-locked emails go through the email adapter (the invitation from the distributor's name) and stay outside the rules.
     - Tests: 7 (consent from the app, staff with and without confirmation, audit; import column; opting out stops waiting WhatsApp; locked preferences; announcements once, WhatsApp only with consent and marketing category; the welcome SMS in the log; account emails). Planted bugs (opt-out leaving waiting messages, no staff confirmation, compulsory switchable, WhatsApp not added for an announcement, announcements sent twice) fail them.
  8. APIs, isolation tests, every key event end to end with the mocks — **done; backend checkpoint**:
     - Staff: inbox and unread badge (own messages), read one or all, own preferences; rules matrix (per event: rules in force, what the tenant changed, WhatsApp on or off, last 30 days' messages, price and cost from the platform's category price, "counts only" until prices are set; shops opted in), replace or reset one event's rules (validated: recipients, channels each recipient can use, texts that exist, staff permissions, compulsory only for the shop; audited); texts per event and language, own in-app and email texts, reset, preview; delivery log with filters, 7-day totals per status, one message with its attempts, retry (audited); announcements; a document's links and revoking them; reminder pause per shop; WhatsApp consent per shop (staff must confirm); upcoming GST rate changes for the dashboard card.
     - Shop: inbox, badge, read, preferences (compulsory and in-app locked), WhatsApp consent with the one-time prompt, current announcements.
     - Super admin: platform texts incl. approved WhatsApp template names, categories and parameters, with preview; failed messages across tenants (audited platform alias, recipients' names left out) with retry.
     - Every key event end to end with the mocks: a shop's welcome SMS, consent, order accepted (with the Order Confirmation link), bill (WhatsApp and email), rejected and cancelled orders, a credit note, a cheque received and bounced, cash, a refund: the exact WhatsApp templates and counts, all naming the distributor first with no unfilled placeholder; emails to the shop; only the welcome by SMS; the shop's and the office's in-app bells; every document link in a WhatsApp message opening its PDF; nothing left pending or failed.
     - Demo data in `make seed`: WhatsApp switched on (mock), every other shop opted in (by staff), one announcement; the seeded orders and bills make their own messages through the worker.
     - Tests: 11 API tests covering roles and another tenant on every new route (34 routes), plus the end-to-end journey; seed test extended. Schema has stable enum names; API client regenerated.
     - Fix pushed separately: a test helper's type (commit 7's CI backend job failed on mypy; my local check had piped mypy through `tail`, hiding its exit status; now run unpiped).
  8b. Checkpoint decisions (ADR-048 "Backend checkpoint") — **done**: all seven approved. The bounced-cheque message now names the cheque's date and the shop's new balance ("Your balance: ₹5,000.00 to pay" / "… in credit" / "nothing to pay"), in-app, email and WhatsApp (migration refreshes the platform texts). Backlog: a distributor's own WhatsApp templates; an optional cheque bounce charge. Tests: the bounce test checks cheque, date, amount and balance; the end-to-end test checks the WhatsApp text.
  9–12. Frontend: notification centre and badge; shop preferences and consent prompt; rules matrix, templates, delivery log, announcements, reminder pauses; platform templates and failures
  13. E2E and responsive check — **final review**
- Phase 5 — Billing, GST, ledger, credit control: **merged to `main` (PR #6, 2026-09-28)**.
- Phase 4 — Ordering & backorders: **merged to `main` (PR #5, 2026-09-28)**.
- **Phase 4 — Ordering & backorders** — **complete; final review approved 2026-09-28, PR #5** (branch `phase-4` from `main` 344b09c; plan approved 2026-09-27 with ADR-044, PLAN §10.2e, SPEC 1.4). Commits in order:
  1. Docs: ADR-044, PLAN (Cart per shop and user, OrderLineDiscount, §10.2e, backlog), SPEC 1.4 — **done**
  2. Models: orders app, `ledger.RetailerAccount`, RLS, checks, append-only history — **done**: carts per (shop, user); orders with settings/address/price snapshots and estimates; lines whose quantity buckets are checked by the database (ordered = pending + reserved + backordered + allocated + cancelled; dispatched ≤ allocated, delivered ≤ dispatched); a row per applied discount; append-only status history; shipments and their lines; backorder allocations. `ledger.RetailerAccount` (balance 0) is created with every shop and backfilled. RLS on all ten tables.
  3. Server cart + shop cart API — **done**:
     - `apps/orders/quote.py` is shared by the cart and order placement. It covers prices from `resolve_prices` (every rule), line tax and totals from `billing/tax.py` (`compute_line` now also takes a discount amount worked out by pricing), and the ready-now / later split.
     - It also reports problems (minimum, multiple, unavailable, not enough stock or partly available with backorders off, minimum order value counting backordered items, shop on hold) and the credit outcome (`apps/orders/credit.py`: the ADR-044 stub; empty limit = unlimited, 0 = no credit).
     - The delivery address (default shipping, else billing) decides the place of supply.
     - Shop API: `shop/cart/` (GET, DELETE), `shop/cart/lines/{product}/` (PUT quantity, 0 removes; DELETE), `shop/cart/reduce-to-available/`, `shop/addresses/`. Every response is the whole priced cart plus `expected_total` for placement.
  4. `place_order` + races (last units, duplicate key, inward vs new order) — **done** (inward vs new order moves to commit 7, with allocation):
     - `apps/orders/services.py` holds the order-date settings snapshot and runs in lock order: the shop account first (L1), then stock levels in product order (L3), then the order number sequence (L6).
     - The same quote as the cart is checked against `expected_total` (`PRICE_CHANGED` keeps the cart; nothing saved). Cart problems give `CART_NOT_READY` with the list; a blocked shop gets `RETAILER_ON_HOLD`.
     - Under the lock, `min(requested, available)` is reserved (RESERVE movements referencing the line) and the rest is backordered (the shops-waiting counter is updated). With backorders off: FAIL (`INSUFFICIENT_STOCK`) or PLACE_AVAILABLE (the rest cancelled).
     - Credit stub: on a breach, ON_HOLD (reserving, or pending when `credit.hold_reserves_stock` is off) or BLOCK (`CREDIT_LIMIT_EXCEEDED`, nothing saved).
     - Saved with the order: `ORD-<year>-000001`, snapshots of product, price (every discount rule in its own row, in the order applied), address, place of supply, settings and totals, plus "Placed by Priya (Sales)" for staff orders. The PLACE/HOLD history, the `order.placed` / `order.on_hold` outbox event and emptying the cart happen in the same transaction.
     - Shop API `POST shop/orders/` (Idempotency-Key): a retry returns the same order (`Idempotent-Replayed: true`).
     - Races: 20 shops ordering 3 each against 10 in stock reserve exactly 10 (with the stock lock removed, 60 were reserved), and 10 simultaneous submissions with one key make one order.
  5. Order state machine + accept/cancel race — **done** (`apps/orders/transitions.py`; shop account then order then stock in every function):
     - Accept (manual, or automatic after the placing transaction commits when the snapshot says AUTO): reserved quantities become shipment `ORD-…/1` (the stock stays reserved until dispatch), and `backorder_state` is OPEN when something waits. An all-backordered order is accepted with no shipment.
     - Reject (reason required) and cancel (the shop, own orders only, before acceptance; or staff): pending, reserved and backordered quantities are released to cancelled, and the stock and shops-waiting counters are updated.
     - Modify before acceptance: REDUCE_ONLY by default, releasing pending, then reserved, then backordered as PLAN §4.1 says. FULL_EDIT (snapshot) can raise quantities or add products; an increase becomes a new line at today's price, so each line keeps its ordered price. Credit is re-checked for additions, and a breach is refused unless a `credit.manage` user gives an override reason (audited). At least one item must remain, and the diff goes into the history and the `order.modified` event.
     - Approving a credit hold reserves or backorders parked quantities by the normal rules (audited).
     - Order totals are recomputed through `billing/tax.py` for what stays open.
     - Race: accept vs cancel on the same order, 10 rounds: exactly one wins each time and the other gets `INVALID_STATE_TRANSITION`.
  6. Shipments: pack, short pack, dispatch, deliver, derived status — **done** (`apps/orders/fulfilment.py`):
     - Pack records the packed quantity per line (0 to the shipment's quantity). The short remainder is released and goes back on backorder, or is cancelled, per the order's snapshot (not today's setting); the history and `order.short_supplied` record it. Packing nothing cancels the shipment.
     - Dispatch: SALE movements consume the reservation, transport details (vehicle, transporter, LR) are kept, and Phase 5 will issue the invoice here. Deliver is done by `orders.fulfil` staff.
     - Staff can cancel a shipment before dispatch (to backorder or cancelled, their choice), or the whole accepted order (every open shipment and the backorder). Neither is possible once anything is dispatched.
     - Order status is derived: COMPLETED when every shipment is delivered and nothing waits, otherwise the least advanced shipment; `backorder_state` stays in step. Freed stock calls the backorder hook.
  7. Backorders: allocation, proposals, cancel remainder, repriced cancel, mixed-operations race — **done** (`apps/orders/backorders.py`):
     - Goods receipts and stock added by adjustments serve waiting backorders in the same transaction (the waiting shops and orders are locked before the stock rows). FIFO by placement time, accepted orders only. A proposal reserves the stock at once.
     - CONFIRM mode (the default): staff confirm proposals in bulk, one backorder shipment per order, or reject one (the stock goes to the next in line; the rejected line keeps its place). AUTO mode confirms in the same run.
     - Credit is re-checked: a shop over its limit is skipped and flagged once (`SKIPPED_CREDIT`, `backorder.skipped_credit`). With a CURRENT billing price, a higher price counts (GST included), and the shipment line is flagged `price_increased`. The shop may decline it until the shipment is packed; the stock then goes to the next in line.
     - Manual allocation: staff choose lines and quantities in any order (no credit re-check: a staff decision). The shop or staff can cancel what a line still waits for.
     - Stock released by a reject, cancel, short pack or cancelled shipment runs allocation after commit.
     - Races: a goods receipt vs a new order (5 rounds; the waiting order always gets the stock), and 30 s of mixed operations across 6 threads and 5 products, weighted so stock stays short (about 2,300 operations locally, including 300+ confirmed proposals; it runs on, up to 90 s, until every key operation has succeeded) (the invariants hold: stock vs movements, reserved = what lines and open shipments hold, backorder demand = what lines wait for). Mutation checks: allocating after commit fails the receipt race; removing the credit re-check, FIFO, AUTO confirm, GST on the price increase, or the proposal's hold each fail a test.
  8. Distributor APIs (+ ordering on behalf), backorder queue, isolation and role tests — **done** (`apps/orders/api/`, PLAN §3.8):
     - Orders: board tabs (new, on hold, backorders, in progress, completed) with filters (shop, salesperson, dates in IST, status, search) and counts (also proposals to confirm and shipments to pack); detail with lines, shipments and timeline; accept (Idempotency-Key), reject, cancel (before or after acceptance), modify before acceptance, credit hold approve/reject (`credit.manage`), cancel what a line still waits for.
     - Shipments: queue, detail, pack (short packs), dispatch with transport details, deliver, cancel before dispatch.
     - Backorders: queue grouped by product (waiting, free stock, held for proposals, shops over their limit), the waiting lines of a product in FIFO order, proposals list, bulk confirm (Idempotency-Key; one shipment per order), reject, manual or automatic allocation.
     - Ordering for a shop: a staff cart per (shop, staff member) under `retailers/{id}/cart/`, placed with `POST orders/` (Idempotency-Key): "Placed by Priya (Sales)". Needs `orders.create_on_behalf` and the setting.
     - Sales staff limited to their own shops (⚙ `orders.sales_visibility`) see and change only those orders, shipments, backorders and carts; other shops' records are "not found".
     - Cancelling an accepted order now ends its open backorder proposals too.
     - Tests: roles for every action, idempotent replay, visibility, and a cross-tenant test over all 25 new routes (reads empty or 404, every change 404, nothing changed). API client regenerated; order enums have stable names.
  9. Shop APIs: home, orders, cancel, repeat, checkout attempts — **done** (`apps/shop/api/orders.py`, PLAN §3.9):
     - Home: the 5 latest orders, "Repeat last order" as product cards (today's price and availability, with last time's quantity; products no longer offered are left out), open orders, products waiting on backorder, and available credit.
     - Orders: list (open or closed), detail with lines, shipments and timeline (the shop sees what happened, not which staff member did it; staff orders say "Placed by Priya (Sales)"), cancel before acceptance, repeat into the cart (adds to what is there; returns the products that can't be ordered any more).
     - Cancel what a line still waits for; decline a higher backorder price until the shipment is packed.
     - `checkout-attempts/{key}`: after a dropped connection the app asks whether its Idempotency-Key placed an order (`placed` with the order, or `not_found`: retry with the same key; an attempt still running then returns its result). Refused attempts leave nothing behind.
     - Tests: every action, and another shop (same tenant or another) sees and changes nothing; staff get 403 on shop routes.
  10. Live updates (WebSocket ticket, consumer, outbox → push) — **done** (`common/live.py`, `apps/orders/tasks.py`):
     - `POST auth/ws-ticket`: a one-time ticket valid for 30 s (the browser can't send the access token on a WebSocket). It carries what the socket may receive, so the socket never touches the database.
     - `/ws/v1/?ticket=…` (same origin: Next proxies `/ws/`, so phones on `make lan` reach it through port 3000): staff who may view orders join their tenant's group; a shop login joins its shop's group. Sales staff limited to their shops get only those shops' events.
     - Every order and backorder event goes out through the outbox (`orders.push_live`, retried with backoff): staff get the event, order, status and shop name; shops get their own orders' events, but not the internal backorder proposals or credit skips. Messages only say what changed; the apps refetch through the API.
     - The outbox now runs local handler tasks with `apply_async` (inline in tests) instead of `send_task`.
     - Checked end to end on the running stack through port 3000 (connect, push over Redis, a reused ticket refused with 403). Tests: tickets (once only, 30 s, platform users refused), who hears what (staff, the shop, another shop, another tenant, sales staff limited to their shops), with mutation checks.
  11. Seed demo orders, API client — **done** (`common/demo_orders.py`); **backend checkpoint**:
     - `make seed` gives each distributor 11 orders across every board tab, through the normal services: new orders (one placed by the salesperson for a shop, one with a delivery note), a credit hold (one demo shop's limit set to ₹500, audited), a rejected and a cancelled order, orders packed, dispatched and completed, accepted orders with items waiting, and one backorder proposal to confirm. Only when a tenant has no orders yet.
     - Seeded on the running stack: 46 live pushes ran on the worker without errors. The API client is regenerated.
  11a. Checkpoint decisions (ADR-045) — **done**: reductions take the waiting quantity first; approving a credit hold records the approved value and covers the order's backorders (a higher CURRENT price is re-checked); blocked shops never get stock (skipped and flagged, refused by hand and on confirm); manual allocation re-checks credit with an audited `credit.manage` override; PARTLY_DELIVERED ("Partly delivered", "N items to follow") replaces the order status DELIVERED, in lists, detail, timeline and filter. Each new rule has a planted-bug check.
  12–13. Shop: quick ordering, cart and checkout, orders — **done** (`web/components/shop/`):
     - The quantity stepper ("Add", then − quantity +, typed quantities too) is on product cards in search, categories and "Order again", and on the product page; it starts at the product's minimum and steps by its multiple (the server still checks). A tap shows at once; taps are gathered and only the last quantity is sent, one request at a time. The cart tab shows the item count. "Ordering coming soon" is gone.
     - Home: search, "Order again" (last order's products as cards with last time's quantity, and "Add all to cart"), your orders, categories.
     - Cart and one-screen checkout: ready now and "Comes later" sections, the server's problems in plain words, "Reduce to what's in stock" when backorders are off, delivery address and instructions, the server's totals, a credit-approval note, and "Place order · ₹total" (pinned above the navigation on phones and tablets). From search to a placed order is 3 taps: Add, Cart, Place order (checked on the running stack at 360 px).
     - Poor connections (ADR-044): one Idempotency-Key per checkout attempt, kept across reloads until the order is placed or the cart changes. After a dropped connection the app asks `checkout-attempts/{key}` before retrying with the same key, and after a reload it finds an attempt that went through.
     - Orders: in progress / past, detail with items (delivered, on the way, being prepared, waiting for stock, cancelled), deliveries, timeline, "Partly delivered · N items to follow", cancel before acceptance, cancel waiting items, decline a higher backorder price until packed, "Order again". Live updates refresh the screens and show a short note.
     - Tests: steps and debouncing, checkout with the same key after a drop (planted-bug checks), reload recovery, plain-word problems; responsive sweep covers the new screens.
  14. Distributor: dashboard, orders board, order detail, shipments, live alerts — **done** (`web/components/orders/`):
     - The dashboard opens on what needs action today: new orders, waiting for credit approval, backorders to confirm, shipments to pack.
     - Orders board: New / On hold / Backorders / In progress / Completed with counts; search, status (incl. Partly delivered) and date filters; cards on phones; "Accept selected" (orders.manage). Nav badges: new + held orders, backorders to confirm.
     - Order detail: accept (Idempotency-Key), change quantities (before acceptance), reject and cancel with a reason for the shop, approve or reject a credit hold (credit.manage), cancel waiting items; shipments with pack (short packs), dispatch (vehicle, transporter, LR), mark delivered, cancel (back to waiting or cancelled); "Approved over the credit limit for ₹…"; timeline with who did what.
     - Shipments queue: to pack, to dispatch, on the way, delivered.
     - Live: new orders and credit holds pop up (with a chime when "Sound on"), stock arriving for backorders links to the queue; every order screen refreshes.
  15. Backorders and ordering for a shop — **done**:
     - Backorders: stock to confirm (bulk confirm, reject to the next order) and the queue by product (waiting, free stock, held for confirmation, approved over limit, over limit, shop blocked). A product's page lists waiting orders oldest first with "Allocate oldest first" or chosen quantities; over the credit limit, `credit.manage` users give a reason to allocate anyway, others are told who can.
     - Order for a shop: pick the shop, search products, a separate staff cart at the shop's prices, delivery address and instructions, Place order (Idempotency-Key); the order says "Placed by …".
  16. E2E acceptance and responsive check — **done** (`web/e2e/orders-acceptance.spec.ts`, in `make e2e-stack` and CI): a fresh distributor; the shop at 360 px goes from search to a placed order in 3 taps; the server places an order but the answer is dropped, and "Try again" finds it (2 orders, not 3); staff accept while the shop's screen changes live; pack, dispatch, deliver: "Partly delivered · 1 item to follow" on both sides; stock arrives, the backorder is confirmed, shipped and the order completes; staff order for the shop. The responsive sweep covers the 9 new screens.
  17. Final review — **approved (2026-09-28)**: the product owner's manual test passed on a real phone over LAN (three-tap ordering, backorders, airplane-mode retry, cancelling) and on a laptop (live orders, accept, short pack, dispatch, deliver, partly delivered, backorder confirmation, credit holds, manual allocation with override, blocked shop, ordering for a shop, permissions), plus stock reservation and release, two shops racing for the last units, prices locked on orders, price changes during checkout, order rules and sales visibility. PR #5 ready for review.
- Phase 3 — Inventory: **merged to `main` (PR #4, 2026-09-26)**.
- **Phase 3 — Inventory** (branch `phase-3` from `main` e117fdf; plan approved 2026-09-26 with ADR-041, PLAN §10.2b, SPEC 1.2). Commits in order:
  1. Docs: ADR-041, PLAN v1.4 (§1.2 S8–S10, §2.7, §3.7, §5, §7.3, §8, §9.1, §10.2b), SPEC 1.2 — **done**
  2. Models: warehouse, stock level, movement, receipts, adjustments, alerts; RLS, checks, append-only trigger, backfills — **done**: RLS on all eight tables; append-only movements and adjustments; a trigger keeps posted receipts unchanged except for completing pending costs once; one open alert per product/warehouse/type; the default warehouse is made with each tenant and every product gets a stock level (both backfilled); movement types have no database list (ADR-041).
  3. Stock primitives (`MOVEMENT_KINDS`, lock order), cost method, concurrency tests — **done**:
     - `lock_levels` (creates missing levels, locks in product order) and `_apply_movement`, the only writer of stock levels. Primitives: receive, add, remove, reserve, release, consume reserved. `INSUFFICIENT_STOCK` and `STOCK_RESERVED` (PLAN S4) are refused before the database checks.
     - Cost method: settings `stock.cost_method` (WEIGHTED_AVERAGE default, LAST_PURCHASE, MANUAL) and `stock.show_out_of_stock_in_shop`. Cost arithmetic in `billing/tax.py` (`cost_per_base_unit`, `stock_value`, `weighted_average_cost`) with table and Hypothesis tests; automatic cost price changes audited with the receipt number.
     - Concurrency tests with real threads and a barrier: 20 threads for the last unit (exactly one reserves), 20 removals from 5 (exactly 5), reservations racing removals, and a 30-second random mix across 5 products in shuffled order (no deadlock past the retry; on hand and reserved equal the movement sums). Removing the row lock makes all four fail.
  4. Alerts: dedupe and outbox events — **done**: `apps/inventory/alerts.py` runs after every movement in the same transaction (and via `refresh_alerts` when a reorder level changes). OUT_OF_STOCK (available ≤ 0), LOW_STOCK (0 < available ≤ reorder level; never with level 0), BACKORDER_DEMAND (backordered > 0). Opening uses `ON CONFLICT DO NOTHING` on the open-alert index; `stock.alert_opened` / `stock.alert_resolved` outbox events only for rows actually opened or resolved, and they roll back with the change. Twenty concurrent evaluations open one alert. Alerts come from stock changes: a new product at zero has no alert until its stock moves.
  5. Goods receipts: draft, post, packs, cost pending, complete costs — **done** (`apps/inventory/receipts.py`):
     - Drafts hold supplier, bill number and date, notes and up to 500 lines. Quantities are entered in the base unit or packs (whole numbers where the unit requires it) and stored in the base unit. The cost is entered per entered unit before GST: the line keeps the bill's cost and total, and the cost per base unit to 4 decimals.
     - Staff without `pricing.view` can't send costs. When they edit a draft, costs they can't see are kept.
     - Posting locks the stock levels, then takes the gap-free `GRN-<year>-00001` number, then updates cost prices. It writes one movement per line and runs the cost method for lines with a cost; lines without one become "cost pending". A backorder hook (`on_stock_received`) is left for Phase 4, and posting is audited. "Save and post" does both in one transaction. The database trigger keeps posted receipts final.
     - `complete_costs` (`pricing.manage`) fills pending lines only and applies the cost method at that moment. The "stock before" is what is on hand now minus that line's quantity (the goods are already in stock), never below zero. It is audited.
     - Race tests: one draft posted by 10 threads posts once, and 10 receipts posted together get numbers 1–10.
     - Test fix: threaded tests skip the after-commit Celery enqueue. Eager tasks in parallel threads could leave Celery's global "inside a task" flag set, which failed a later test in CI.
  6. Adjustments: reason + note, add / remove / counted, reserved guard, audit — **done** (`apps/inventory/adjustments.py`):
     - One adjustment covers up to 500 products, each at most once. It has a reason code and a required note. Lines add, remove or record a counted quantity; the server works out the difference, and a count that matches is reported as unchanged with no line written. Whole numbers where the unit requires them.
     - Numbered `ADJ-<year>-00001`, gap-free. The DAMAGE reason writes DAMAGE movements; other removals write ADJUSTMENT_OUT. Removing reserved stock fails the whole adjustment with `STOCK_RESERVED`, naming the product and how much can be removed. Audited as `stock.adjusted` with each line's before and change.
     - Reorder level: `set_reorder_level` (audited as `stock.reorder_level_changed`) re-checks alerts. A product edit that changes the reorder level does too; it locks the stock level before the product, the same order receipts use.
  7. Stock APIs and reports (low stock, valuation) with isolation and role tests — **done** (`apps/inventory/api`, `selectors.py`):
     - Routes: `warehouses/` (+ PATCH, `settings.manage`), `stock/` (search, category, brand, status IN_STOCK/LOW/OUT/BACKORDERED), `stock/summary/` (open alerts by type; receipts awaiting cost only for `pricing.view`), `stock/lookup/?code=` (barcode or code, for scanning), `stock/{product}/` (+ `reorder-level/`: `products.manage` or `stock.adjust`), `stock/movements/`, `stock/alerts/`, `stock/inwards/` (+ detail, `post/`, `complete-costs/`), `stock/adjustments/` (+ detail), `reports/stock/low-stock/` and `reports/stock/valuation/` (+ `products/`, both with Excel export).
     - POSTs that create receipts or adjustments, post a receipt or complete costs need an Idempotency-Key; a repeat returns the original result.
     - Receipts can be read with `stock.inward` or `pricing.view`, so pricing users can open "Goods receipts awaiting cost". Valuation needs `reports.stock` and `pricing.view`.
     - `HasPermission` accepts `AnyOf(...)` / `AllOf(...)`, and the role matrix and permission-code tests understand them.
     - Cost fields are null without `pricing.view`: receipt costs, movement unit cost and value, and the cost price on the stock page.
     - Valuation rounds each product's value to the paisa before summing, so the page, the totals and the export agree. Products without a cost price are marked, left out of every total and counted. Category (full path) and brand totals are included in the export.
     - Tests: one isolation test covers all 20 routes (lists, detail by id, writes, exports), plus hidden costs, awaiting cost, idempotent posting, pack entry and lookup, adjustment errors, reorder-level roles, filters, valuation and warehouse rename. API client regenerated.
  8. Shop availability labels, `stock.show_out_of_stock_in_shop`, opening stock import — **done**:
     - `apps/inventory/availability.py`: shop products carry `availability {status, quantity}`. The status is IN_STOCK, LOW_STOCK (only with `stock.show_low_stock_label`), BACKORDER (nothing available, backorders on) or OUT_OF_STOCK. The quantity is shown only with `stock.show_exact_quantity`. Available means on hand minus reserved.
     - With backorders off and `stock.show_out_of_stock_in_shop` off, products with nothing available are hidden from lists, detail, category counts and brands.
     - Opening stock import (`OPENING_STOCK`, needs `stock.adjust`):
       - Columns: product code, quantity, optional "Cost per unit (before GST)" (restricted to `pricing.manage`, refused as an error without it).
       - Modes of its own, chosen every time: "Add to stock" or "Set stock to this count". Import kinds now declare their modes.
       - Each changed row is posted as an "Opening stock" adjustment. A cost runs the cost method, or is noted as unused when the stock goes down or the method is "Never". Stock can't be set below what is reserved.
     - `GET stock/export/` gives today's stock as a count sheet in the same columns.
     - The import wizard doesn't offer the new kind yet; that comes in frontend commit 12.
     - Test fix: the per-IP sign-in limit test pins the limiter's clock, because the fixed one-minute window could split its 31 attempts (a flaky CI failure).
  9. Seed demo stock, API client — **done; backend checkpoint**: each demo tenant gets opening stock, a shelf count that empties some products and leaves some low (so both alert types show), a posted goods receipt with costs, one posted by the warehouse without costs (awaiting cost), a draft and a damage adjustment. This happens once only (skipped when stock documents exist). Checked on the running stack: alert counts, the out-of-stock filter, valuation, and the warehouse view of a receipt awaiting cost (costs hidden; valuation refused).
  9a. Checkpoint follow-ups (ADR-042, PLAN §10.2c, SPEC 1.3) — **done**:
     - `costs.view` / `costs.manage`: Owner, Manager and Accounts see costs; Owner and Manager change them; not Sales or Warehouse. They replace the pricing permissions for costs everywhere: product cost price (API, import and export column, product form), receipt costs, the awaiting-cost list and count, movement cost and value, valuation, complete costs, and cost on adjustments and the opening stock import.
     - A test walks every GET route of the tenant API as Sales and as Warehouse with real ids, and finds no cost figure in any JSON, Excel or CSV response. A control run as Accounts finds the figures. Putting the old `pricing.view` gate back on products makes the walk fail.
     - The opening stock import is one adjustment per file. The import framework now reports rows that were valid at validation but fail the re-check at commit, instead of skipping them silently.
     - Low-stock summary: `reports/stock/low-stock/summary/` gives the low count and the active products without a reorder level. The stock list filter `no_reorder_level=true` shows them.
     - Dev database: the demo products' missing cost prices were backfilled (dev data only, done once from a shell).
  10. Frontend: stock overview, product stock page, movements — **done**:
      - `/manage/stock`: count cards (low, out, shops waiting) that filter the list. A notice links to "N goods receipts are waiting for costs" (for `costs.view`). Search, status filter (including "No reorder level", also reachable via `?status=`), category and brand. Cards on phones. "Receive goods", "Adjust stock", the count-sheet download and opening stock import appear only for staff with those permissions.
      - `/manage/stock/[product]`: available, on hand, reserved and waiting figures; the reorder level editor (`products.manage` or `stock.adjust`); cost price (`costs.view` only); open alerts; barcodes; paginated movement history.
      - `/manage/stock/movements`: filter by type and date. Each row links to its goods receipt or adjustment, and the value column appears only when the server sends values.
      - A stock card on the product page. A stock sub-navigation. The sidebar "Stock" item shows the open-alert count, refreshed every minute.
  11. Frontend: goods receipt entry — **done**:
      - `ScanBar` (receipts, and adjustments next):
        - a USB/Bluetooth scanner or a typed code plus Enter looks up the exact product (`stock/lookup`), and typing a name shows 44 px matches;
        - the camera button uses the browser's `BarcodeDetector`, or else `barcode-detector` (zxing-wasm), loaded only when the camera opens. The `.wasm` is copied into `public/vendor` before `dev`/`build`, so it's served by us, never a CDN;
        - over plain http (LAN) the camera explains that it needs https, as ADR-041 item 14 says;
        - an unknown code can be linked to a product on the spot (`products.manage`).
      - `/manage/stock/inwards/new` and draft editing:
        - Phones: products as cards, the base-unit or pack choice, large −/+ steppers, and the bill details folded under "Supplier and bill" so scanning comes first.
        - Laptops: a grid where Enter goes from quantity to cost and back to the scan bar.
        - Scanning the same product again adds one. The cost field shows only with `costs.view`; warehouse staff see "Costs are added later…" and never send a cost.
        - "Save as draft" / "Save and post" with a confirmation. Server messages appear next to their line.
        - Every create, post and cost save sends an Idempotency-Key, made with `crypto.getRandomValues`. The live check on the LAN found that `crypto.randomUUID` doesn't exist on plain http, so the page had crashed there; that is fixed and tested.
      - `/manage/stock/inwards`: All / Drafts / Posted / Waiting for costs (`costs.view`). The posted receipt shows received packs and the base-unit equivalent, and has the "Add the missing costs" form (`costs.manage`).
      - Lockfile: regenerated with the image's npm (node:24-alpine). My local npm had dropped optional entries, which made `npm ci` fail in Docker.
      - Checked on the running stack at 360 and 1440 px as warehouse and owner: no sideways scrolling, scanning a code adds the line and selects its quantity.
  12. Frontend: adjustments, alerts, reports, opening stock import — **done**:
      - `/manage/stock/adjustments/new`: reason chips (required), a required note and the same `ScanBar`. Each line is Counted (default), Add or Remove, shows what is in stock now, and has a large quantity field. It posts with an Idempotency-Key and reports how many counts matched. The adjustment list and detail pages show before and change for each line.
      - `/manage/stock/alerts`: Open / Resolved, filter by type.
      - `/manage/reports/low-stock`: shortfall per product, Excel export, and "N active products have no reorder level" linking to the filtered stock list.
      - `/manage/reports/stock-valuation` (`reports.stock` + `costs.view`; others get a plain "needs cost access" message): total value, products valued, a "without a cost price" count that filters the list, category/brand totals and Excel export.
      - `/manage/reports`: an index of the reports that exist so far.
      - The import wizard offers "Opening stock" with its own modes ("Add to stock" / "Set stock to this count"); choosing another kind clears the mode.
      - Checked on the running stack at 360 and 1440 px as warehouse and owner: no sideways scrolling.
  13. Frontend: shop stock labels — **done**: product cards and the product page show the server's label (In stock, Low stock, Available on backorder, Out of stock) with the product's status colours, and "3 pieces in stock" only when the distributor shows exact stock. Nothing about stock is worked out in the shop.
  14. E2E acceptance, responsive check, docs — **done; waiting for the final review**:
      - `e2e/inventory-acceptance.spec.ts` (in `make e2e-stack` and CI):
        - a new distributor imports 3 products and a shop, and sets a reorder level of 5;
        - it receives 12 by typing the code and pressing Enter (as a scanner does), with cost 7.50, and posts: GRN-…-00001, a ₹90.00 line and total, the movement on the product page, and cost price ₹7.50;
        - two damage adjustments (−9, −1) leave one open low-stock alert, not two;
        - at 360 px the shop sees "Low stock" with no quantity and "Available on backorder" for a product never received, with no sideways scrolling.
        
        It passed locally (5/5) on the stack in localhost mode. One earlier run failed at the super admin's 2FA step ("That code didn't work"): the Mac and container clocks agree, and the next runs passed. I'll keep an eye on it.
      - Responsive check: 15 new screens (stock, product stock, movements, alerts, receipts list/new/posted/draft, adjustments list/new/detail, reports index, low stock, stock value, stock settings). `e2e_ids` gives the receipt and adjustment ids. Two phone problems it found were fixed: the "More stock actions" button was 38 px wide, and the folded bill fields on the receiving page still took space (now a toggle that renders them only when open). All screens pass at 360/768/1440.
      - Phone receipt cards show the line cost up front.
      - CLAUDE.md: how to enable the camera over `make lan` (a Chrome flag on Android; typed and USB/Bluetooth scanners need nothing).
  15. Final review follow-ups (ADR-043, PLAN §10.2d) — **done**:
      - The stock value report is open to `costs.view` with `reports.stock` or `reports.financial`, so Accounts sees it. Requirements nest (`AllOf`/`AnyOf`), and the role matrix, permission-code test, frontend check and API test (Accounts and Manager 200, Warehouse and Sales 403) all agree.
      - Flaky 2FA sign-in, root cause: clock skew after the Mac slept. The Docker VM clock was about 5 minutes behind until its 30-second time sync caught up; the `pmset` and Docker `GET /time` logs show it. It wasn't replay.
      - The server now logs the refusal reason (`replay`, `clock_skew:±n`, `invalid`). The E2E helper computes the code from the backend's clock (`e2e_totp_state`), never reuses a step (it waits for the next), avoids the last 3 seconds of a step, and fails at once with the reason.
      - Proof runs:
        - 30 sign-ins passed with the old helper, which ruled out replay between runs.
        - With the new helper: 20 normal sign-ins; 6 back-to-back sign-ins without the reset, landing on 6 different steps (the old helper would have been refused on 5 of them); and a deliberate replay, reported as "replay".
        - Then the four full-stack suites 3 times in a row and the responsive check.
- **Phase 3 acceptance (spec §12):** receipts and adjustments update stock with the right movements, alerts fire once, and the concurrency tests pass (backend threads plus the lock mutation check). Shops see the labels at 360 px.
- Phase 2 — Catalog, retailers, pricing: **merged to `main` (PR #3, 2026-09-26)** after the product owner's manual testing (all three combination modes, special prices, shop view, cost price visibility, copy pricing, imports, responsive layouts on a real phone). Plan approved 2026-09-25 with ADR-034 … ADR-036. Commits in order:
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
  - Commit 9: `pricing/resolve.py` implements `resolve_price` and a batch form, `resolve_prices`, per spec 5.6 and ADR-036.
    - Unit price comes from the shop's special price, then its price list, then the base price.
    - Only the single best rule applies. Ties are broken by amount, then audience, then scope (a category rule also covers its sub-categories), then the newest rule. Slabs use the highest one reached.
    - New setting `pricing.discounts_on_special_prices` (default on).
    - Uses the GST rate in effect on the day. Inactive, deleted or not-yet-taxed products raise `PRICE_UNAVAILABLE`.
    - Staff endpoints: `POST pricing/preview/` and `GET retailers/{id}/prices/` (a shop's price sheet).
    - 44 resolver tests, including both values of the new setting and Hypothesis properties.
  - Commit 10: shop catalog API (`apps/shop`, retailer logins only, scoped to the login's own shop).
    - `shop/categories/`: the tree with product counts; empty categories are hidden.
    - `shop/brands/`: added to PLAN §3.9 for the brand filter.
    - `shop/products/`: browse by name, filter by category (with sub-categories) or brand. A search returns the top 40 ranked matches.
    - `shop/products/{id}/`: images and slab hints ("24 or more: ₹9.50 each").
    - Visibility follows ADR-034, with an implementation note added there. Prices come from `resolve_price` at the minimum order quantity. The shop never sees base prices, price sources or rule names.
    - A page costs a fixed number of queries.
    - Isolation tests: the other distributor's shops, staff, and staff routes. Shops on hold follow `retailers.blocked_can_sign_in`.
  - **Backend checkpoint reached.**
  - Checkpoint follow-ups (approved 2026-09-25):
    - The shop price now includes the discount amount and `discount_per_unit`, alongside the MRP.
    - Free-goods warning (`FREE_GOODS`) when saving a discount rule or special price that makes products free. Added to ADR-036, and free-goods schemes are on the PLAN backlog.
    - The search performance test uses the median of 5 runs (limit still 200 ms).
    - New test: MRP changes are highlighted in the import change preview.
  - Commit 11: distributor catalog screens.
    - Products list: search, filters for category, brand, status and shop visibility; bulk actions; Excel/CSV export.
    - Product form (React Hook Form + Zod; decimals stay strings). It shows server warnings, and the GST hint for the HSN code.
    - Edit page panels: GST-rate history with schedule and cancel, photos (background processing polled until ready), barcodes.
    - Category tree (3 levels), brands and units.
    - New `GET products/tax-options/`: the GST rates and cess types in use (platform reference data).
    - Shared additions: `SubNav`, `FormSelect` (links labels to selects; also fixed in `FieldsDialog`), `downloadFile` for binary downloads, and `useDebounced`.
  - Commit 12: import wizard (`/manage/imports/new`, `/manage/imports/{id}`, `/manage/imports`).
    - Start page: choose products or retailers (with the template download), choose the mode explicitly (no default; the button stays disabled until one is chosen), then the file.
    - Job page: polls while the file is checked or imported. Shows the counts, skipped columns, and row errors with row and column.
    - Change preview: old → new values, with price and MRP changes highlighted. Confirm with "Import N rows". Then the result, with any rows skipped at commit.
    - Full xlsx report download and an import history.
  - Commit 13: retailer screens.
    - List: search; filters for status, salesperson and price list; bulk assign salesperson or price list, put on hold (with a reason) or remove the hold; export; import.
    - Create form: profile, GSTIN, state, language, salesperson, price list, and an optional billing address. The welcome message is sent on create.
    - Detail page: edit, resend the welcome message, hold or remove the hold, delete.
    - Credit card: editable only with `credit.manage`. Addresses: add, edit, remove.
    - "What this shop pays": the server's price sheet at each product's minimum quantity, showing the price source and discount.
  - Commit 14: pricing screens (`/manage/pricing/...`).
    - Price lists: create, rename, delete; a list's products with inline price edits and add or remove.
    - Special prices: all shops, or one shop from its page; shop and product pickers that search as you type.
    - Discount rules: list with status filter. Editor for percentage or rupees per unit, quantity slabs, scope (all products, category with sub-categories, brand, one product), audience (all, price list, one shop), dates and on/off.
    - The `FREE_GOODS` warning shows with the product owner's wording. After a create that warns, the editor stays open and later saves update the same rule.
    - Settings groups "Pricing" (`pricing.discounts_on_special_prices`) and "Shops" (`retailers.blocked_can_sign_in`).
  - Commit 15: shop catalog, read-only (`/shop`, `/shop/catalog[/{category}]`, `/shop/search`, `/shop/products/{id}`).
    - Pages: home greeting with categories and search; category tiles with counts; brand chips; product cards ("show more" paging); product page with photos, the "Buy more, pay less" slab hints and pack size.
    - Prices exactly as the server sends them: net price, struck-through price and the saving when discounted, MRP, and "+ GST" or "incl. GST".
    - Minimum quantity and order steps are shown in plain words. The on-hold notice appears on every catalog page.
    - Ordering arrives in Phase 4; the product page says so.
    - Sign-out fix: after signing out, the next sign-in lands on the shop home page, not the page the person left.
  - Commit 16: seed, E2E acceptance, docs.
    - `make seed` adds, per distributor (`common/demo.py`):
      - a 3-level category tree, 12 brands and 200 products with photos (a few hidden or inactive);
      - "Gold" and "Wholesale" price lists;
      - 20 shops (some with a GSTIN, on price lists, with salespeople; one on hold) and 5 special prices;
      - 5 discount rules: category slabs, a brand week, a price-list rule, a future Diwali offer and a switched-off rule.
    - The seed goes through the normal services, is idempotent, and takes about 18 s locally. `--no-photos` skips the photos.
    - `e2e_workbook` (DEBUG only) makes real .xlsx import files for the browser test.
    - `e2e/support/flows.ts` holds the onboarding steps shared by both acceptance specs.
    - The full-stack specs run one at a time (`--workers=1`), because the super admin's 2FA codes are single-use.
- **Phase 2 review additions** (2026-09-26; ADR-037 … ADR-039, PLAN tasks 2.20–2.28):
  - Docs commit: spec 5.4/5.6, PLAN (M5, tasks, settings, backlog incl. manufacturing, decisions 10.2a), ADR-037 … ADR-039.
  - 2.20: a ₹0 price-list price warns "This price list makes N products free for M retailers…" (shops with their own special price for the product don't count); shown on the price list screen.
  - 2.21: discount combination (ADR-038), new setting `pricing.discount_combination`: `BEST` (default), `ADD` or `SEQUENTIAL`.
    - `resolve_price` returns every rule applied, in order, plus the total and the percentage (`billing.tax.percent_of`). The total is capped at the line; in `ADD` the least specific rule is trimmed.
    - The shop API sends only the total: `discount_total`, `discount_percent` and `discount_per_unit`. The shop shows "You save ₹0.50 each (5%)"; slab hints unchanged.
    - Staff price sheets show the total, the % and the rule names.
    - 28 new resolver tests: each mode with percentages, flat plus %, slabs, the cap, sequential order and special prices, plus Hypothesis properties.
  - 2.22: own brand and cost price (ADR-039).
    - `Brand.own_brand` (audited), an own-brand filter and badge on the product list, and setting `retailers.show_own_brand_badge` (default off) for the shop badge.
    - `Product.cost_price`: returned only with `pricing.view` (null otherwise), set only with `pricing.manage` (checked in the service, so imports too), audited as a price change. Never in the shop API.
    - Imports: a "Cost price" column that needs `pricing.manage`. Templates and exports leave the column out without `pricing.view`.
    - The seed adds an own brand ("Sharma Select" / "Patel Select") and cost prices.
  - 2.23–2.26: per-shop pricing tools, backend (`apps/pricing/tools.py`, `api/tools.py`).
    - Discount grid: `GET/PUT retailers/{id}/discount-grid/` and `POST …/preview/`.
      - One simple rule per shop and product (no slabs, no dates), named "R-00001 · CODE". Slab or dated rules come back read-only.
      - The preview prices the entered discounts through `resolve_prices` with rules supplied for the preview only; nothing is saved.
      - Saving writes one audit entry (`pricing.shop_discounts_changed`) and returns a free-goods warning when needed.
    - Copy pricing: `POST retailers/{id}/copy-pricing/preview/`, then `…/copy-pricing/` with `expected_changes`.
      - Replace or Add, no default. A stale preview returns 409 `PREVIEW_OUT_OF_DATE`.
      - Copies the price list, special prices, and shop rules with their slabs. Copied rule names switch to the target shop's code.
      - In Add, a simple rule replaces the target's. One audit entry, `pricing.pricing_copied`.
    - Bulk % change: `POST price-lists/{id}/adjust/preview/`, then `…/adjust/` with `expected_count`.
      - Category (with sub-categories) or brand; optionally adds the missing products from the standard price.
      - Rounding to the paisa or to whole rupees, half-up (`billing.tax.adjust_price`).
      - Audited: the price changes plus `pricing.price_list_adjusted`.
    - Shop pricing report: `GET pricing/shop-report/` (customised shops or all, with counts and free products; 25 per page) and `…/export/`, plus `GET retailers/{id}/free-products/`.
      - Free products are found by a cheap upper bound on each rule's share (best, or the sum), then full pricing for the at-risk products only.
    - Every route has isolation tests and is in the role matrix.
  - 2.27: pricing imports and exports (`apps/dataio/kinds/pricing.py`), each needing `pricing.manage`; exports need `pricing.view`.
    - Special prices: shop by mobile or code, product code, price, note. The pair is the key; ₹0 warns.
    - Price-list prices: an existing list by name (unknown names list your lists), product code, price.
    - Discount rules:
      - The name is the key, and rows with the same name are one rule, one row per slab.
      - Targets: product code, brand, or category path. Audience: a price list or a shop (mobile or code).
      - Type % or ₹. Dates as DD-MM-YYYY or Excel dates (`parsing.parse_date`).
      - Rows of one rule must agree, and one bad row skips the whole rule. In "update existing", a name shared by several rules is an error.
      - The preview shows names, not ids, and highlights discount changes. A 100% discount warns.
    - Exports use the template columns, so a file can go out and come back with no changes; tested for all three.
    - The wizard offers the three new kinds. Shared test fixtures moved to `apps/dataio/tests/conftest.py` and `helpers.py`.
  - 2.28a: frontend, retailer page.
    - "What this shop pays" edits the special price in place (the price sheet now returns each row's special price); clearing it removes the price.
    - A "Pricing for this shop" card with:
      - "Discounts by product": the discount grid at `/manage/retailers/{id}/discounts`. Server-priced net prices update as you type, and "Save N changes" saves them. Slab or dated rules show as "Also: …" links. Read-only without `pricing.manage`.
      - "Add a discount for this shop": the rule editor, pre-filled for the shop.
      - "Copy pricing from another shop": pick a shop, choose Replace or Add (no default), preview, then "Copy N changes".
  - 2.28b: frontend, pricing section.
    - Price lists: "Change prices by %" (brand or category, optionally add missing products, paisa or whole-rupee rounding, server preview, then "Update N prices").
    - Shop pricing page (`/manage/pricing/report`): customised or all shops, counts linking to the shop's special prices and discount grid, free products in a dialog, Excel export.
    - Export and import buttons for special prices, price-list prices and discounts.
    - The "When several discounts apply" setting is on the Pricing settings page (from the registry).
  - E2E `e2e/pricing-tools.spec.ts` (in `make e2e-stack` and CI). Passed locally with the other two specs (17 passed).
    - A new distributor imports 20 products and 4 shops.
    - The grid previews ₹10.35 for 10% off ₹11.50 and saves; a special price is set in place.
    - Pricing is copied (Replace) after a preview.
    - At 360 px the second shop sees "You save ₹1.15 each (10%)" and the ₹9.00 special price.
    - Gold gets +5% for one brand with the missing products added (5 prices), and the report lists both shops.
  - **Phase 2 review additions complete; waiting for review.**
  - Fixes after manual testing: the missing descriptions of the Pricing and Shops settings pages (a test now renders every settings group); the shop now uses the width of tablets and laptops.
  - **Responsive design (ADR-040, CLAUDE.md §6a):**
    - Lists become cards below 1024 px, each with its own card fields.
    - Bulk selection on phones uses a "Select" mode with a bottom action bar.
    - On phones: filters in a bottom sheet (`FilterBar`) and Save/Cancel stuck to the bottom of long forms (`FormActions`).
    - 44 px touch targets in the design system. The audit log also shows cards on phones.
    - `e2e/responsive.spec.ts` checks 57 screens at 360, 768 and 1440 px: no sideways scrolling, no off-screen or overlapping controls, 44 px targets on phones. Screenshots are the CI artifact `responsive-screenshots`; locally `make e2e-responsive`.
  - **Phone testing on the home network:** `make lan` / `make localhost` (`infra/dev-domain.sh`).
    - The switch detects the LAN IP and writes the git-ignored `infra/dev-domain.env` (platform domain `<ip>.nip.io` and public storage address), which Compose layers over `.env`. It then recreates the containers and clears cached branding links.
    - Dev-only settings follow the domain: Next `allowedDevOrigins` and Django CORS.
    - Postgres, Redis, the API and Mailpit are now bound to 127.0.0.1; only web and storage are reachable from the LAN.
    - Checked over nip.io at phone size: staff sign-in and reload, shop OTP sign-in, the chooser hand-off, and product photos from the LAN address.
- **Phase 2 acceptance (spec §12), passed on the local stack and wired into CI (`e2e-stack`).** In `e2e/catalog-acceptance.spec.ts`:
  - A new distributor imports 1,000 products and 100 retailers from Excel, and adds a price-list price.
  - At 360 px, a shop on the price list sees ₹5.00 and a shop without it sees the standard ₹11.50.
  - Neither shop finds the other distributor's seeded products. Pages don't scroll sideways, and signing out leads to plain sign-in.
  - The same run passed `acceptance.spec.ts` (Phase 1) after the flows were shared.

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
| 8 | WhatsApp provider (undecided): implement the real adapter against its official API; confirm that one number may send on behalf of several businesses, template approval and categories, the template body length limit, delivery/read webhooks (signature checked), and how incoming "STOP" replies reach us (to record opt-outs). Only the mock exists; deployed environments refuse it (`notifications.E001`). SMS texts must match DLT-registered templates (item 4) | `backend/apps/notifications/adapters/whatsapp.py` | Chosen provider's API docs and terms | Product owner (provider choice) + lead engineer | Open (before staging) |
| 9 | Amazon SES for email: verified sending domain (SPF, DKIM, DMARC), production access (out of the sandbox), bounce/complaint handling, the SendEmail request shape and which error codes are permanent; set `EMAIL_PROVIDER=ses` in production | `backend/apps/notifications/adapters/email.py` | AWS SES documentation | Lead engineer | Open (before staging) |

## Known issues / pending
- ADR-009 (tax engine & rounding) is still pending CA confirmation: `docs/CA_REVIEW.md` (22 questions) and the sample PDFs in `docs/ca/` go to the CA; the defaults stay until then.
- PDFs render only where WeasyPrint's libraries are installed (the backend image, CI). Host-run backend code on macOS can't print them unless `PDF_RENDERER=fake`.
- Shop return requests are on the backlog.
- Production domain to be supplied before staging (ADR-019).
- Next.js dev-server redirects built from `request.url` use the dev server's own host when the Host header is forged (curl). Real browsers are unaffected. Revisit if a reverse proxy sits in front in dev.
