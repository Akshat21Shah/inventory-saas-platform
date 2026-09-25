# Architecture & Product Decision Records

Format: each ADR has a status, date, context, decision and consequences. ADRs are never edited after acceptance except to change their status. A reversal is a new ADR that supersedes the old one.
Details of each design live in `docs/PLAN.md`. The section references (§) below point there.

| ADR | Title | Status |
|---|---|---|
| 001 | Stack, app layout, identifiers, precision | Accepted |
| 002 | Tenant isolation | Accepted |
| 003 | Transactional outbox | Accepted |
| 004 | Global lock order | Accepted |
| 005 | Idempotency keys | Accepted |
| 006 | Per-shipment fulfilment model | Accepted |
| 007 | Invoice timing, short packs, Order Confirmation | Accepted |
| 008 | GST rate master & effective-dated product rates | Accepted |
| 009 | Tax engine & rounding rules | **Accepted — pending CA confirmation** |
| 010 | Place of supply & supply type | Accepted |
| 011 | Invoice immutability & numbering | Accepted |
| 012 | Tenant GST registration type | Accepted |
| 013 | Credit exposure & credit control | Accepted |
| 014 | Backorder allocation policy | Accepted (amended by 021) |
| 015 | Retailer identity per tenant | Accepted |
| 016 | Configurability principle & settings registry | Accepted |
| 017 | Payments: advances, cheques, allocation | Accepted |
| 018 | Suspended tenants | Accepted |
| 019 | Environment: domain & object storage | Accepted (storage amended by 024) |
| 020 | Login hosts for staff and super admin | Accepted |
| 021 | Repriced backorders — retailer cancellation | Accepted |
| 022 | Follow-up business rules (2026-09-25) | Accepted |
| 023 | Phase 0 tooling choices | Accepted |
| 024 | SeaweedFS as the dev/CI S3 stand-in | Accepted |
| 025 | Auth tokens, refresh cookie & session lengths | Accepted |
| 026 | Identity tables & cross-tenant login lookups | Accepted |
| 027 | Storage adapter & asset serving | Accepted |
| 028 | Brand palette derived on the client | Accepted (amends PLAN §2.2) |
| 029 | Impersonation: read-only by default, audited "act" mode | Accepted (amends PLAN T7) |
| 030 | Login protection, staff 2FA, owners, subdomain & tenant lifecycle | Accepted |
| 031 | Field-level encryption | Accepted |
| 032 | Neutral "unavailable" tenant state, reset limit setting, trusted proxies | Accepted (amends 018, 025, 030) |

---

## ADR-001 — Stack, app layout, identifiers, precision
- **Status:** Accepted — 2026-09-24
- **Context:** `CLAUDE.md` §2 locks the stack. Several implementation-level choices were still open.
- **Decision:**
  - Use the locked stack unchanged.
  - Django apps live under `backend/apps/`. The platform app is `apps.platform`: it is always imported with the `apps.` prefix, and a lint rule forbids a bare `import platform` inside `apps/` (it would shadow the stdlib module).
  - Primary keys are UUIDv7, generated in Python (`common.ids.uuid7()`). Human-facing numbers (order, invoice) are separate fields.
  - Precision types: `Money` = Decimal(14,2); `Qty` = Decimal(14,3); `Rate` = Decimal(6,3), because half of 0.25% is 0.125; `UnitCost` = Decimal(14,4), used only for unit/average cost.
- **Consequences:** Keys are non-enumerable and index-friendly. The rule "money is 2 dp" has one documented exception: unit cost.

## ADR-002 — Tenant isolation
- **Status:** Accepted — 2026-09-24
- **Context:** Zero cross-tenant access is the top non-functional requirement.
- **Decision:**
  - Every tenant model inherits `TenantScopedModel`. Its default manager filters by the tenant context variable and raises if none is set.
  - Each authenticated request runs in a transaction that sets `app.current_tenant` via `set_config(…, true)`. RLS policies on every tenant table enforce it.
  - The application DB role has no BYPASSRLS; migrations run as the owner role.
  - Super-admin cross-tenant access uses a separate DB alias, reachable only through audited `platform` services.
  - Celery tasks receive `tenant_id` explicitly. Cache keys, Channels groups and storage keys are tenant-prefixed.
  - An isolation test is generated for every URL pattern.
- **Consequences:** Every request is transactional (small overhead). Forgetting a filter fails closed.

## ADR-003 — Transactional outbox
- **Status:** Accepted — 2026-09-24
- **Context:** `on_commit` → Celery loses events if the broker is unavailable right after commit.
- **Decision:**
  - Services write `OutboxEvent` rows in the same transaction as the business change.
  - `on_commit` triggers dispatch, and a beat sweeper re-dispatches anything undispatched after 60 s.
  - Consumers (notifications, real-time, PDFs, e-invoice) are idempotent on `event_id`.
- **Consequences:** At-least-once delivery, no lost events. Consumers must tolerate duplicates.

## ADR-004 — Global lock order
- **Status:** Accepted — 2026-09-24
- **Context:** Orders, stock inward, dispatch, allocation and payments lock overlapping rows.
- **Decision:**
  - A single order, always: L1 `RetailerAccount` (by retailer id) → L2 `Order`/`Fulfilment` → L3 `StockLevel` (by product id, warehouse id) → L4 backorder `OrderLine`s (FIFO) → L5 `Invoice` → L6 sequences/series.
  - Stock-increasing operations use a two-phase pattern: read candidates without locks, then take locks in order, then re-verify.
  - Top-level services retry on deadlock (3 attempts, jittered).
- **Consequences:** Deadlocks become rare and self-healing. Violating the order is a code-review blocker. Details in PLAN §5.1.

## ADR-005 — Idempotency keys
- **Status:** Accepted — 2026-09-24
- **Decision:**
  - The `Idempotency-Key` header is required on order placement, payment recording/intents, acceptance, allocation, credit notes and ledger adjustments.
  - Records are unique per (user, endpoint, key), store the request hash + response, and are kept for 24 h.
  - Same key with a different body → 422. Concurrent duplicate → 409.
- **Consequences:** Clients can safely retry on poor mobile networks.

## ADR-006 — Per-shipment fulfilment model
- **Status:** Accepted — 2026-09-24 (product owner)
- **Context:** A single order status cannot represent a delivered first shipment with an open backorder.
- **Decision:**
  - Every shipment (the initial one and each backorder allocation) is a `Fulfilment`, with its own packing, dispatch, invoice and status (ALLOCATED → PACKED → DISPATCHED → DELIVERED / CANCELLED).
  - Order statuses gain **COMPLETED** = all shipments delivered and no open backorder quantity.
  - After acceptance, the order status is derived from the least-advanced open shipment.
  - `OrderLine` quantity buckets always satisfy `ordered = pending + reserved + backordered + allocated + cancelled`.
- **Consequences:** One order can have many invoices (as the spec already allows). The distributor "Completed" tab = COMPLETED + REJECTED + CANCELLED.

## ADR-007 — Invoice timing, short packs, Order Confirmation
- **Status:** Accepted — 2026-09-24 (product owner)
- **Decision:**
  - Tenant setting `invoicing.timing` = `ON_DISPATCH` (**default**) | `ON_ACCEPTANCE`, snapshotted per order.
  - **ON_DISPATCH:** the invoice is issued at dispatch for the **packed** quantities. A short-packed remainder goes to backorder if backorders are enabled; otherwise it is cancelled and the retailer is notified.
  - **ON_ACCEPTANCE:** the invoice is issued at acceptance / backorder allocation. A short pack is corrected with a `SHORT_SUPPLY` credit note, and the remainder follows the same backorder-or-cancel rule.
  - The e-way bill is always generated from the invoice at dispatch.
  - `orders.send_confirmation_on_accept` (default on) sends an **Order Confirmation** document (items, prices, tax estimate — explicitly not a tax invoice) at acceptance, through the normal notification channels.
- **Consequences:** In the default mode, invoices match what physically ships, so short-supply credit notes are rare. Credit exposure counts accepted-but-undispatched shipments as uninvoiced order value (ADR-013).

## ADR-008 — GST rate master & effective-dated product rates
- **Status:** Accepted — 2026-09-24 (product owner)
- **Context:** GST rates were rationalised effective 22-Sep-2025 (GST 2.0). Rates change over time and must be schedulable.
- **Decision:**
  - A platform master `TaxRate`, seeded **active** 0, 0.25, 3, 5, 18, 40 and **inactive** 12, 28. Inactive rates stay valid on historical invoices and their credit notes, but cannot be assigned to new product rate rows.
  - Platform masters `CessType` and an optional `HsnRateHint` (suggestions and import warnings only; never used to compute tax).
  - Product tax is stored in append-only, effective-dated `ProductTaxRate(gst_rate, cess_type, cess_rate, effective_from)`. Future-dated rows schedule a change. One selector, `tax_rate_on(product, date)`, is the only way to read a rate.
- **Consequences:** Rate changes need no code deploy. Bulk scheduling by HSN/category is provided.

## ADR-009 — Tax engine & rounding rules
- **Status:** **Accepted — pending CA confirmation (product owner to confirm before Phase 5 starts).**
- **Decision:**
  - All tax logic lives in `apps/billing/tax.py`.
  - Tax is computed per line on the post-discount taxable value. CGST and SGST are each computed from taxable at half the rate and rounded independently, so they are always equal.
  - GST-inclusive prices: the discount applies to the inclusive amount, and taxable is backed out per line. A ±₹0.01 line tolerance is absorbed by the round-off.
  - Defaults: component rounding `HALF_UP`, invoice rounded to the rupee (`NEAREST`, half-up) with a round-off line.
  - Tenant settings, limited to vetted lists: `tax.component_rounding` ∈ {HALF_UP, HALF_EVEN}; `invoicing.round_to_rupee` (bool); `invoicing.round_off_method` ∈ {NEAREST, UP, DOWN}.
  - Credit notes prorate taxable, and the credit that exhausts a line (or an invoice) takes the exact remainder.
  - Document totals are always the sum of line components, and every document reconciles to the paisa.
  - The worked examples in PLAN §6.3 are fixed unit tests. Tests cover every value of every tax setting.
- **Consequences:** If the CA changes a rule, only `tax.py`, its tests and the allowed-value lists change.

## ADR-010 — Place of supply & supply type
- **Status:** Accepted — 2026-09-24 (product owner). **Fixed rule.**
- **Decision:**
  - Place of supply = the state of the order's shipping address, defaulting to the retailer's registered state.
  - Same state as the tenant → CGST + SGST; different → IGST. Not configurable.

## ADR-011 — Invoice immutability & numbering
- **Status:** Accepted — 2026-09-24 (product owner). **Fixed rules.**
- **Decision:**
  - Issued invoices are never edited or cancelled; corrections go through credit notes. The only exception is e-invoice IRN cancellation within the officially permitted window (Phase 7; window to be verified against official rules).
  - Numbering is gapless, per tenant, per financial year (April–March, computed in IST), ≤ 16 characters, `A–Z 0–9 / -`.
  - Numbers are allocated from a locked series row inside the issuing transaction. The prefix/format is configurable per series within these limits.
  - Credit notes and receipts use their own series.
  - Invoices snapshot the rounding/timing settings in effect when issued. The price basis (incl./excl. GST) comes from the order snapshot.

## ADR-012 — Tenant GST registration type
- **Status:** Accepted — 2026-09-24 (product owner)
- **Decision:**
  - Every tenant must have a valid GSTIN in v1.
  - Setting `tax.registration_type` offers only `REGULAR`. `COMPOSITION` (bill of supply) is reserved and disabled in validation.
- **Consequences:** Adding composition later means enabling the value and adding a bill-of-supply document type. No data migration is needed.

## ADR-013 — Credit exposure & credit control
- **Status:** Accepted — 2026-09-24 (product owner)
- **Decision:**
  - **Fixed formula:** `exposure = ledger balance + value (incl. GST) of all open not-yet-invoiced order quantities + this order`.
  - Checks are serialized per retailer by locking the `RetailerAccount` row.
  - Empty credit limit = unlimited; `0` = no credit.
  - Settings:
    - `credit.breach_action` = REQUIRE_APPROVAL (**default**) | BLOCK;
    - `credit.hold_reserves_stock` (default true; false parks quantities in `qty_pending` until approval);
    - `credit.block_overdue_after_days` (default off).
  - Credit is re-checked when allocating backorders, and retailers over their limit are skipped and flagged.
  - Pending (uncleared) cheques do not reduce exposure.

## ADR-014 — Backorder allocation policy
- **Status:** Accepted — 2026-09-24 (product owner); amended by ADR-021
- **Decision (fixed):**
  - FIFO by order placement time, with older backorders served before new orders.
  - Only accepted orders are eligible.
  - Allocation runs inside the same transaction as the stock increase (inward, adjustment-in, restock), so new orders cannot take the stock first.
  - Proposals awaiting confirmation hold (reserve) the stock. Rejecting a proposal releases it to the next in line.
- **Decision (settings):**
  - `backorders.enabled` (default true);
  - `backorders.allocation_mode` = CONFIRM (**default**) | AUTO;
  - `backorders.billing_price` = ORIGINAL (**default**) | CURRENT (re-resolved when the allocation is confirmed).
  - Permission `orders.allocate_backorder` is granted by default to Owner, Manager and Warehouse.

## ADR-015 — Retailer identity per tenant
- **Status:** Accepted — 2026-09-24 (product owner). **Supersedes spec 5.5 "mobile unique platform-wide".**
- **Decision:**
  - A retailer's mobile is unique **per tenant**. The same person or shop can hold separate retailer accounts under different distributors: each is its own `Retailer` + RETAILER `User` (with a `tenant` FK), with fully separate data.
  - Retailers log in on their distributor's subdomain.
  - On the generic domain, after OTP verification, if the number matches retailers in more than one active tenant, a "choose your distributor" screen is shown (only to the verified phone owner). The chosen tenant is entered through a single-use handoff code.
  - OTP request responses are identical whether or not a number is known.
  - Nothing ever tells a distributor that a number exists under another tenant.
- **Consequences:** No cross-tenant uniqueness leaks. Staff users remain globally unique by email.

## ADR-016 — Configurability principle & settings registry
- **Status:** Accepted — 2026-09-24 (product owner)
- **Decision:**
  - Business rules that are not firm are configurable; legal and data-integrity guarantees are fixed in code (list in PLAN §9).
  - A typed registry in code (`apps/platform/registry.py`) defines each setting's key, group, scope, type, default, allowed values, edit permission, plain-language description, snapshot targets and dependencies.
  - Only overrides are stored (`TenantSetting` / `PlatformSetting`), so a new tenant works on defaults.
  - The settings UI is generated from the registry, grouped Tax / Invoicing / Orders / Stock / Credit & Payments, with descriptions shown.
  - Orders, invoices and credit notes snapshot the settings in effect at creation. Later changes never alter existing documents.
  - Every change is audited (who, old, new, when).
  - Tests cover every value of every relevant setting and the zero-override tenant.
- **Consequences:** More test combinations (parametrised). Feature flags remain separate: flags gate whole modules; settings tune behaviour.

## ADR-017 — Payments: advances, cheques, allocation
- **Status:** Accepted — 2026-09-24 (product owner)
- **Decision:**
  - `payments.hold_advances` (default true): excess money is held as unapplied credit and auto-applied FIFO to future invoices.
  - `payments.cheque_credit_timing` = ON_RECEIPT (**default**, an automatic reversing entry on bounce) | ON_CLEARANCE (no ledger entry until cleared; a bounce has no ledger effect).
  - Payments allocate FIFO by default or manually. Reversals are new negative allocations plus reversing ledger entries, never edits.
  - Online payment status changes only from verified webhooks or reconciliation.

## ADR-018 — Suspended tenants
- **Status:** Accepted — 2026-09-24 (product owner). **Fixed rule.**
- **Decision:**
  - Suspension blocks all staff and retailer logins for that tenant with a friendly message, and stops its scheduled jobs.
  - All data is kept. Super admin can view, impersonate (audited) and reactivate.

## ADR-019 — Environment: domain & object storage
- **Status:** Accepted — 2026-09-24 (product owner); storage part amended by ADR-024
- **Decision:**
  - The platform domain comes from the env `PLATFORM_DOMAIN`. Dev uses `localhost`: `admin.localhost`, `{slug}.localhost`, and bare `localhost` as the generic domain. The production domain will be supplied before staging.
  - Object storage is accessed only through the storage adapter. MinIO in Docker Compose stands in for S3 in development and CI.

## ADR-020 — Login hosts for staff and super admin
- **Status:** Accepted — 2026-09-25 (product owner)
- **Decision:**
  - **Distributor staff** log in on their tenant subdomain, or on the generic `<PLATFORM_DOMAIN>/login` with email + password (+ TOTP if enabled).
    - On the generic domain, the tenant is resolved from the user's active memberships. With more than one, a tenant chooser follows.
    - The session is moved to `{slug}.<domain>` with a single-use, 60-second handoff code, so refresh cookies stay scoped to the tenant subdomain.
  - **Retailers:** as ADR-015 (subdomain, or the generic domain with a distributor chooser after OTP).
  - **Super admin** (PLATFORM users) log in **only** at `admin.<PLATFORM_DOMAIN>`. Platform users are refused on other hosts, and staff are refused on the admin host, with the same generic error (no account enumeration).
  - Host classification (`ADMIN`, `TENANT(slug)`, `GENERIC`) is done once, in middleware, from `PLATFORM_DOMAIN`.

## ADR-021 — Repriced backorders: retailer cancellation
- **Status:** Accepted — 2026-09-25 (product owner). Amends ADR-014.
- **Decision:** With `backorders.billing_price = CURRENT`, the price is fixed when the allocation is confirmed.
  - If the new price is **higher** than the order price, the fulfilment line is flagged `price_increased`. The retailer is notified, and may cancel that quantity themselves at any time **until the shipment is packed**. The cancellation releases the reserved stock (FIFO re-runs for the next waiting retailer), and the quantity moves to cancelled.
  - In ON_ACCEPTANCE invoice mode, the already-issued invoice is corrected with a `CANCELLATION` credit note.
  - If the price is unchanged or lower: notification only.

## ADR-022 — Follow-up business rules (2026-09-25)
- **Status:** Accepted — 2026-09-25 (product owner)
- **Decision:**
  1. **Price basis:** an invoice interprets its order's prices using the order's `tax.prices_include_gst` snapshot. Rounding uses the invoice-time snapshot.
  2. **FULL_EDIT and credit:** a pre-acceptance edit that would breach the credit limit is refused (`CREDIT_LIMIT_EXCEEDED`), unless a user with `credit.manage` applies an override in the same flow. The override requires a reason and is audited (`credit.override_applied`).
  3. **`payments.hold_advances = false`:**
     - offline payments above the outstanding amount are refused (`PAYMENT_EXCEEDS_OUTSTANDING`);
     - a credit note that exceeds the invoice balance still leaves a credit balance (legally owed), which is applied to the next invoice.
  4. **Scheduled GST rate changes:**
     - with GST-inclusive prices, the inclusive price is kept and the taxable value changes;
     - a daily job warns distributors **7 days** before any rate change affecting their products, both as a dashboard card and as a notification (`tax.rate_change_upcoming`), listing the affected products.
  5. **Order Confirmation:** the acceptance document is titled "Order Confirmation" and carries the line **"This is not a tax invoice."**

## ADR-023 — Phase 0 tooling choices
- **Status:** Accepted — 2026-09-25 (technical decision; lead engineer)
- **Decision:**
  - **Python 3.13** in the venv, Docker and CI (satisfies "3.12+"). Django **5.2 LTS**, DRF 3.18, Celery 5.6, Channels 4.3.
  - **uv** manages backend dependencies with a committed `uv.lock`. It is installed inside `backend/.venv` and the image, never globally.
  - **uvicorn** serves ASGI (HTTP + WebSockets).
  - **python-json-logger** plus a context filter produces JSON logs carrying `request_id`, `tenant_id` and `user_id`.
  - **Next.js 16** (App Router, Turbopack), with the Next 16 conventions:
    - `proxy.ts` replaces the deprecated `middleware.ts`;
    - `skipTrailingSlashRedirect`, so Django's trailing-slash URLs survive the `/api/*` rewrite;
    - page URLs are normalised to no trailing slash in `proxy.ts`.
  - Frontend libraries: Tailwind v4 + shadcn/ui (radix base), TanStack Query 5, TanStack Table **v9** (`useTable` + `tableFeatures`), next-intl 4 (cookie locale, no locale in URLs), React Hook Form + Zod 4.
  - **npm** as the package manager. The lock file is generated with the Node 24 container's npm so `npm ci` works identically on macOS, in Docker and in CI.
  - **orval** generates typed TanStack Query hooks from `backend/openapi.yaml` into `web/lib/api/generated`, through the `apiFetch` mutator. An npm `overrides` entry pins a patched `undici` for orval's parser (a dev-only dependency).
  - The browser calls the API **same-origin** (`{slug}.<domain>/api/*` → Next rewrite → Django, with `X-Forwarded-Host`), so cookies stay scoped to the tenant subdomain.
  - Sentry (backend `sentry-sdk`; frontend `@sentry/nextjs` via `instrumentation*.ts`) initialises only when a DSN is configured.
  - `platform` and `accounts.User` exist in Phase 0 only as **minimal stubs** (a custom user model must exist before the first migration, and `TenantScopedModel` needs a Tenant FK target). Phase 1 completes them.
  - The outbox table is **not RLS-protected**: the dispatcher reads it across tenants, and payloads carry identifiers only. Every other tenant table must have RLS, and a test fails CI if one doesn't.

## ADR-024 — SeaweedFS as the dev/CI S3 stand-in
- **Status:** Accepted — 2026-09-25 (technical decision; amends ADR-019). Supersedes "MinIO in Docker Compose".
- **Context:** The `minio/minio` and `minio/mc` images are no longer publicly pullable (Docker Hub repository removed; quay.io requires authentication). The product-owner decision was about having *an* S3 stand-in behind the storage abstraction, not about MinIO specifically.
- **Decision:**
  - Use **SeaweedFS** (`chrislusf/seaweedfs`, Apache-2.0) with its S3 gateway on port 8333, dev credentials from `infra/seaweedfs/s3.json`, and bucket `inventory-dev` created by a one-shot `s3-init` service using the same image.
  - All application code talks to storage only through the storage adapter (boto3 / S3 API, Phase 1). Production uses AWS S3.
- **Consequences:** Nothing S3-specific changes in application code. If you prefer another stand-in (e.g. RustFS, LocalStack), it is a Compose-only swap.

## ADR-025 — Auth tokens, refresh cookie & session lengths
- **Status:** Accepted — 2026-09-25 (technical decision approved by the product owner; session lengths by the product owner)
- **Context:** Spec 5.2 asks for a short-lived access JWT and a refresh token in an httpOnly cookie for the web. Cookies must stay scoped to one tenant subdomain (ADR-020, ADR-023).
- **Decision:**
  - The access JWT (10 minutes) carries `sub`, `tid` (tenant, or none for platform users), `utype` and, when impersonating, `imp` (session id) and `imp_mode`. It is kept **only in memory** in the browser and sent as `Authorization: Bearer`.
  - The refresh token lives in an httpOnly cookie: `Secure` outside dev, `SameSite=Lax`, **host-only** (no `Domain` attribute, so it never reaches another subdomain), `Path=/api/v1/auth/`. It rotates on every use, and the old token is blacklisted (simplejwt blacklist).
  - CSRF defence for the cookie-authenticated endpoints (`token/refresh`, `logout`, `handoff/exchange`): the request must carry `X-Requested-With: fetch`, and its `Origin` must match the host.
  - Refresh lifetimes by user type: **retailer 30 days, sliding** (each rotation restarts the window); **staff 7 days**; **super admin 12 hours**. Impersonation tokens are never refreshable (ADR-029).
  - On each refresh and on each authenticated request, the tenant status and the user's active membership or retailer account are re-checked (cached briefly and invalidated on change), so suspension and deactivation take effect at once (ADR-018).
  - The frontend makes one refresh attempt on a 401, shared by all waiting requests, then retries. Area shells guard on the client; the API enforces everything regardless.
- **Consequences:** XSS cannot read the refresh token, and a page reload costs one refresh call. Mobile (Phase 11) stores the refresh token in secure storage and sends it in the body instead of a cookie.

## ADR-026 — Identity tables & cross-tenant login lookups
- **Status:** Accepted — 2026-09-25 (technical decision approved by the product owner)
- **Context:** Login has to find users before any tenant is known. Examples: staff on the generic domain, resolved by their memberships (ADR-020), and a verified phone on the generic domain, which may match retailers in several tenants (ADR-015).
- **Decision:**
  - `accounts_user` is an identity table **without RLS**, because it is read before a tenant is known. It holds no business data. The RLS-coverage test lists it as an explicit exemption, with this reason.
  - Tenant-owned identity data (`Membership`, `Invitation`, `Retailer`, `OTPRequest` with a tenant) is tenant-scoped with RLS.
  - Cross-tenant lookups at login use **two narrow selectors** on the platform (BYPASSRLS) alias, and each call is logged:
    - `staff_memberships_for_login(user)`, which returns active memberships in active tenants;
    - `retailer_accounts_for_verified_phone(phone)`, which runs only after the OTP is verified and returns active retailer accounts in active tenants.
  - No other code uses the platform alias for login.
  - `Role` rows with `tenant = NULL` are system roles. Their RLS policy lets every tenant read them, but no tenant can write them.
- **Consequences:** Account discovery is limited to someone who has proved identity (a password or OTP), and it never reveals other tenants to a distributor.

## ADR-027 — Storage adapter & asset serving
- **Status:** Accepted — 2026-09-25 (technical decision approved by the product owner)
- **Decision:**
  - `common.storage` defines a `Storage` interface (`put`, `open`, `delete`, `presigned_get`) with two implementations: S3, via boto3 (AWS in prod, SeaweedFS in dev and CI, ADR-024), and in-memory (tests).
  - Object keys are prefixed by tenant: `tenants/{tenant_id}/branding/{kind}/{uuid}.{ext}`.
  - Uploads are validated on the server: PNG, JPEG or WebP only, with the type checked from content by Pillow and not from the file name. The limit is 2 MB. **SVG is refused**, because it can carry scripts.
  - Public branding assets (logo, favicon, app icon) are served at a stable API URL that redirects (302) to a short-lived presigned URL, so pages can cache the stable URL.
  - The signatory image is never public; only staff with `settings.manage` can read it.
- **Consequences:** The bucket stays private, and moving to another S3-compatible store changes only configuration.

## ADR-028 — Brand palette derived on the client
- **Status:** Accepted — 2026-09-25 (technical decision approved by the product owner). **Amends PLAN §2.2** (`TenantBranding.palette` is dropped).
- **Decision:** The server stores only `primary_color`. The 50–950 palette and the foreground colour are derived in `web/lib/theme/palette.ts`, which is already tested; the React Native app (Phase 11) will reuse the same TypeScript. The server validates only the hex format.
- **Consequences:** Deriving a palette is presentation, not business logic, so the thin-client rule still holds. There is one source of truth for the derivation.

## ADR-029 — Impersonation: read-only by default, audited "act" mode
- **Status:** Accepted — 2026-09-25 (product owner). **Amends PLAN §1.2 T7.**
- **Decision:**
  - A super admin starts an impersonation session with a required reason. Sessions start **READ-ONLY**: every write request (any method other than GET, HEAD or OPTIONS) is refused with `IMPERSONATION_READ_ONLY`.
  - The super admin can switch the session to **ACT** mode by entering a separate reason. The switch is audited (`impersonation.act_enabled`), and so is every write made in the session: each audit entry records the impersonator and the session.
  - **Always blocked, even in ACT mode:**
    - changing the target user's password, 2FA or email;
    - staff and role management (invitations, role changes, deactivation);
    - bank details;
    - payment gateway and GST credentials (Phase 7).

    These endpoints are marked `impersonation_blocked`, and a test fails if any endpoint in the listed groups isn't marked.
  - Super admins cannot be impersonated. Staff and retailers can be.
  - A session lasts at most `platform.impersonation_session_minutes` (default 30). The token cannot be refreshed. Ending the session, or the token expiring, closes it.
  - Session events (start, switch to ACT, end or expiry, with reasons) are written to the **tenant's** audit log, so the tenant's owners see them in `/manage/audit`. Platform users see them in `/platform/impersonations`.
  - The frontend shows a persistent banner with the target, the mode, the remaining time and an "End session" button.
- **Consequences:** Support staff can look without risk, and every change is traceable. Some support fixes need the ACT step on purpose.

## ADR-030 — Login protection, staff 2FA, owners, subdomain & tenant lifecycle
- **Status:** Accepted — 2026-09-25 (product owner)
- **Decision:**
  1. **Lockout:** 5 consecutive failed logins lock the account for 15 minutes. A successful login resets the count, and so does a successful password reset, which also unlocks the account. When an account is locked, the user is sent an email (via Celery, enqueued with `on_commit`).
  2. **Rate limits:** Indian mobile carriers put many users behind shared IPs (CGNAT), so per-IP limits are generous and per-account limits do the real protection.
     - Login: 30/min per IP, 5/min per email.
     - OTP request: 3 per 10 min per phone, 100/hour per IP.
     - OTP verify: at most 5 attempts per code.

     All of these values are **platform settings** (PLAN §9.2, group Security). A throttled response is `RATE_LIMITED` with `Retry-After`.
  3. **Staff 2FA:** a tenant setting `security.require_staff_2fa` (default off; edit permission `settings.manage`, which only the Owner system role holds). When it is on, staff without TOTP must enrol at their next login before getting a session. 2FA remains mandatory for super admins.
  4. **Owners:** a tenant may have several owners. The last active owner cannot be demoted or deactivated, and an owner cannot deactivate themself.
  5. **Subdomain:** only a super admin can change a tenant's slug, after a warning that bookmarks, installed apps and sessions on the old address stop working. It is audited. Distributors see it read-only.
  6. **Tenant lifecycle:** a new tenant is `ONBOARDING` until the owner accepts the invitation, then becomes `ACTIVE` automatically. While it is ONBOARDING, a super admin can resend the owner invitation (the previous link is revoked). A super admin can suspend a tenant from ONBOARDING or ACTIVE (ADR-018) and reactivate it.
- **Consequences:** Shared-IP users aren't locked out together. Lockout emails tell account owners about attacks. Security limits can be tuned without a deploy.

## ADR-031 — Field-level encryption
- **Status:** Accepted — 2026-09-25 (technical decision; lead engineer)
- **Decision:**
  - `common.crypto.EncryptedTextField` encrypts values with `cryptography`'s `MultiFernet` (AES-128-CBC + HMAC-SHA256). Keys come from `FIELD_ENCRYPTION_KEYS`, a comma-separated list whose first key encrypts and all keys decrypt, so keys can rotate.
  - A management command, `rotate_encrypted_fields`, re-encrypts stored values with the current first key.
  - Prod settings refuse to start without a key. Dev and test use a fixed, clearly non-secret key.
  - Encrypted fields cannot be searched or indexed. They are masked in API responses (for example `••••1234`) and in audit diffs.
  - Encrypted in Phase 1: the bank account number and the TOTP secret. Phase 7 adds gateway and GSP credentials.
- **Consequences:** A database dump alone doesn't reveal secrets. Losing all keys loses the data, so keys go in the secrets manager with a backup (runbook in Phase 10).

## ADR-032 — Neutral "unavailable" tenant state, reset limit setting, trusted proxies
- **Status:** Accepted — 2026-09-25 (product owner, Phase 1 backend checkpoint). Amends ADR-018 (message), ADR-025 (public branding) and ADR-030 (limits).
- **Decision:**
  1. **Neutral tenant state.**
     - Outside the platform team, a tenant is only *available* (ACTIVE) or *unavailable* (any other state: onboarding, suspended, or anything added later). The specific status is never disclosed.
     - Public branding returns `available: true|false` instead of the status.
     - Every sign-in attempt for an unavailable tenant gets one answer, `TENANT_UNAVAILABLE`: "This account is currently unavailable. Please contact your distributor." That covers staff login on its subdomain (before any credential check), retailer OTP request and verify, the generic-domain choosers (for a verified owner), handoff exchange, refresh, and every authenticated request.
     - Exceptions: invitation links stay usable while ONBOARDING (accepting the owner's invitation activates the tenant), and support impersonation (ADR-018).
  2. **Reset limit.** The forgot-password limit (default 3 per email address per hour) is the platform setting `platform.password_reset_per_email_per_hour`.
  3. **Forwarded headers.**
     - The web server (`web/server.mjs`, a custom Node server in front of Next.js) discards every client-supplied `X-Forwarded-For`/`-Host`/`-Proto`/`-Port`, `Forwarded` and `X-Real-IP`, and sets them from the connection.
     - Only when the connecting peer is in the web server's `TRUSTED_PROXIES` (the production load balancer) is its `X-Forwarded-For` consulted, taking the rightmost address that is not a trusted proxy.
     - Django trusts forwarded headers only from its own `TRUSTED_PROXIES` (the web server's addresses). `TrustedProxyMiddleware`, first in the chain, removes them from every other peer. This applies in dev and prod.
     - uvicorn runs with `--no-proxy-headers` in both images.
     - In Compose, the web container has a fixed address (172.30.0.10) that Django trusts. Direct requests to port 8000 cannot choose their IP.
- **Consequences:**
  - Per-IP rate limits and audit IPs cannot be spoofed from the browser, and only the load balancer set-up remains to verify before launch.
  - `next dev`/`next start` are replaced by `node server.mjs` (Turbopack and HMR still work).

