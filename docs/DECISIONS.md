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
| 033 | Phase 1 review follow-ups: platform-alias reads, branding cache, dev 2FA key, GSTIN rules | Accepted |
| 034 | Catalog: search, product visibility and product images | Accepted |
| 035 | Data import framework | Accepted |
| 036 | Pricing resolution and retailer settings | Accepted |
| 037 | Managing pricing per shop at scale | Accepted |
| 038 | Combining discounts | Accepted (amends 036) |
| 039 | Own brand and cost price | Accepted (amended by 042) |
| 040 | Responsive design: cards, filter sheet, sticky actions, three checked widths | Accepted |
| 041 | Inventory: stock movements, cost method, costs after posting, what shops see | Accepted (amended by 042) |
| 042 | Cost permissions separate from pricing; one opening-stock document per file | Accepted (amends 039, 041; valuation access amended by 043) |
| 043 | Stock value for Accounts; E2E 2FA codes from the backend's clock | Accepted (amends 042) |
| 044 | Ordering before billing: credit stub, staff carts, addresses, flaky-network checkout, quick ordering | Accepted |
| 045 | Reductions, credit at allocation, blocked shops, partly delivered | Accepted |
| 046 | Billing before e-invoicing: numbering, documents, returns, salesman collections, ageing, advances | Accepted |

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


## ADR-033 — Phase 1 review follow-ups: platform-alias reads, branding cache, dev 2FA key, GSTIN rules
- **Status:** Accepted — 2026-09-25 (product owner, end-of-phase review).
- **Decision:**
  1. **Platform alias reads after writes.**
     - The `platform` alias is a separate connection, so it cannot see the current request's uncommitted rows.
     - A view whose write handler reads through it opts out of the request transaction, commits its write in its own `atomic()` block, then reads (`CommitThenReadView`).
     - `common/tests/test_platform_alias_reads.py` finds every function that reaches `platform_db(...)` (directly or through module-level helpers) and fails if a write handler reaches one inside the request transaction.
  2. **Public branding cache.**
     - The pre-login branding response is cached per tenant slug in Redis (`public_branding:<slug>`, 10-minute safety TTL).
     - It is invalidated on commit by every change that affects it: branding and brand images, business name, web address (old and new), status (suspend, reactivate, owner activation).
     - Unknown slugs are not cached. Brand image URLs carry a version (`?v=`) that changes with the stored object.
     - The web server does not cache it (every page gets the current state from Redis).
  3. **Dev 2FA key.** The public key that `manage.py seed` sets (`DEV_TOTP_SECRET`) is guarded in three places:
     - The seed and `reset_e2e_limits` refuse to run unless DEBUG is on.
     - `mfa.matching_step` never accepts the key when DEBUG is off.
     - The production image runs `check --deploy --database default --fail-level ERROR` before starting uvicorn. `accounts.E003` fails if any account has the key. `accounts.E004` fails if 2FA secrets cannot be decrypted (for example a development database). The image also sets `DJANGO_SETTINGS_MODULE=config.settings.prod`.
     - Prod settings also refuse the dev field-encryption key (ADR-031).
  4. **GSTIN rules.**
     - Spaces are removed and letters uppercased before validation.
     - The state code must be an active GST state, including 97 (Other Territory, accepted by the product owner on 2026-09-25).
     - The PAN holder type (6th character) must be one of A, B, C, F (firms, including LLPs), G, H, J, L, P, T. Source: the Income Tax Department's official list of PAN holder types, verified by the product owner on 2026-09-25.
     - Character 13 is 1–9 or a letter, character 14 is Z, and the check character must match (the error adds "Check for mix-ups like O/0, I/1 or S/5.").
     - Every error names the wrong part.
     - A GSTIN is unique across tenants; the same PAN in another state is a separate tenant.
     - The PAN is never an input: it is characters 3–12 of the GSTIN.
     - The same rules apply to onboarding, super admin edits and the distributor's business settings.
  5. **E2E repeatability.** `manage.py reset_e2e_limits` (DEBUG only) clears rate-limit counters for the test accounts and all per-IP counters, and resets their lockout and 2FA replay state. Playwright runs it in global set-up and before each sign-in step, so no test waits for a time window.
- **Consequences:** Phase 5 adds the GST identity lock after the first invoice (PLAN task 5.13).

## ADR-034 — Catalog: search, product visibility and product images
- **Status:** Accepted — 2026-09-25 (product owner, Phase 2 plan).
- **Decision:**
  1. **Search.** Products carry a `search_vector` maintained by a database trigger (name and codes/barcodes weight A, brand and tags B, category C), with GIN indexes starting with the tenant. Trigram similarity on name and code catches typos. One selector ranks full-text matches, then trigram similarity. Target < 200 ms on 20,000 products, checked by a CI test.
  2. **What retailers see.** A product appears in the shop only if it is active, not deleted, has "Show in shop" on (a per-product switch, default on, independent of active/inactive, for internal items), has a GST rate in effect today, and `resolve_price` returns a valid price for that retailer. Products whose only rate is in the future stay hidden until it takes effect.
     *Implementation (commit 10):* every rule except the last is filtered in SQL, together with "unit price above zero" (special price, then price list, then base price), so category counts and pages stay cheap. A product that only a 100% discount brings to zero is dropped from the page after pricing. Its category count may then be one too high, which is acceptable for such a rare setup. The shop never sees the base price, the price source or rule names.
  3. **Scheduled GST-rate changes.** Rate history is append-only. A change dated in the future can be cancelled before it takes effect: it is marked cancelled (audited), never deleted. Rates in effect can never be changed retroactively; a correction is a new future-dated change.
  4. **Product images.** JPEG/PNG/WebP up to 5 MB, validated like brand images (ADR-027). A background task makes thumbnail, medium and large WebP variants. Variants are stored under unguessable, content-versioned keys (`…/products/<product>/<random token>-<content hash>/<size>.webp`) with `Cache-Control: public, max-age=31536000, immutable`, and served through the storage/CDN layer at a stable URL. A new URL is generated only when the image changes, so browsers and CDNs cache images indefinitely (important on mobile data). Keys are never listed publicly. Originals stay private.
- **Consequences:** Product image URLs are public-but-unguessable (like most CDNs); anyone holding a URL can view that image, which is acceptable for catalog photos. Production CDN configuration is on the pre-production list.

## ADR-035 — Data import framework
- **Status:** Accepted — 2026-09-25 (product owner, Phase 2 plan).
- **Decision:**
  1. **Flow.** Upload (xlsx or csv) → background validation of every row without saving (dry run) → report with counts (new, updated, unchanged, errors) and a downloadable row-level error report (xlsx) → the distributor commits → valid rows are applied in the background. Templates (xlsx) per kind.
  2. **Mode chosen explicitly for every import** (no default): *Add new only* (existing codes/mobiles are reported as errors) or *Add new and update existing* (only columns present in the file change; a blank cell means "no change"; a retailer's mobile number and login are never changed).
  3. **Change preview** for update imports: old and new value for every changed field, with price and MRP changes highlighted, and the total number of rows that will change. Price changes via import are audited exactly like manual changes.
  4. **Messy files are normal.** Blank rows and columns are skipped; merged or padded header cells, trailing spaces, numbers stored as text, prices with commas and the ₹ symbol, and CSV files in UTF-8 (with or without BOM), UTF-16 or Windows-1252 are handled. Duplicate keys within one file, missing required columns, wrong GST rates and invalid HSN codes are errors. Every error names the row (as numbered in the file) and the column, in plain language.
  5. **Implementation choices (lead engineer).**
     - The uploaded file stays the source of truth: commit re-reads and re-checks it, so rows changed since validation are reported, and a retried commit never applies a row twice.
     - Each valid row is applied in its own transaction through the normal services (audited as manual changes).
     - Missing brands and categories (up to 3 levels, written `Food > Biscuits`) are created and shown in the preview.
     - An update import never changes a GST rate: that needs a start date, so it is scheduled under GST rates.
     - HSN codes of odd length are read with the leading zero Excel drops (`402` → `0402`, noted on the row).
     - The error report is an authenticated xlsx download, not a public link.
     - Exports use the template's columns, so a file can go out, be edited and come back.
- **Consequences:** Imports are never partially applied by accident: nothing is saved until the distributor confirms a validated file.

## ADR-036 — Pricing resolution and retailer settings
- **Status:** Accepted — 2026-09-25 (product owner, Phase 2 plan).
- **Decision:**
  1. `pricing.services.resolve_price(retailer, product, qty, on)` implements spec 5.6 with PLAN M1–M6: unit price = retailer special price → retailer's price list → base price; discount = the single best active rule (highest amount, then audience retailer > price list > all, then scope product > deeper category > brand > all, then newest); category rules cover sub-categories; flat discounts are per unit, capped at the line gross; the highest slab reached by the line quantity applies (a rule with slabs and no reached slab does not apply). Line math comes from `apps/billing/tax.py`.
  2. New tenant setting `pricing.discounts_on_special_prices` (default **true**): when false, a retailer-specific price is the final net price and no discount rule applies to it.
  3. New tenant setting `retailers.blocked_can_sign_in` (default **true**): when true, blocked retailers can sign in, browse and see their account with the notice "Your account is on hold. Please contact your distributor."; ordering is blocked (Phase 4). When false, sign-in is refused with the same neutral message.
  4. **Free goods are not supported yet** (backlog). A discount rule or special price that brings a product's net price to zero is saved, with the warning "This rule makes N products free for M retailers. Free-goods schemes are not supported yet." (code `FREE_GOODS`; a special price says "This special price makes…"). Each shop's own unit price is used, and the rule's highest slab counts. The count covers active products shown in the shop, and active shops. Rules that are switched off or have ended don't count; rules that start later do. The products stay hidden from those shops (ADR-034).
  5. (2026-09-26) A ₹0 price-list price shows the same warning: "This price list makes N products free for M retailers." Rule 1's "single best rule" is now the default of a setting (ADR-038).
- **Consequences:** Both settings are evaluated live (no snapshot) until orders exist; Phase 4 snapshots the price basis on the order line.

## ADR-037 — Managing pricing per shop at scale
- **Status:** Accepted — 2026-09-26 (product owner, Phase 2 end-of-phase review).
- **Context:** Hundreds of shops and thousands of products. Per-shop pricing must be quick to set up and must not become a hidden mess.
- **Decision:**
  1. **What this shop pays** (retailer page): the server's price sheet, with the special price edited in place, and "Add a discount for this shop" (a rule pre-filled for the shop, by product, brand or category).
  2. **Discount grid for one shop.** All products, searchable and filterable by category and brand. Staff with `pricing.manage` enter the shop's discount per product (% or flat per unit), and the server previews the net price as they type. Saving creates, changes or removes that shop and product's **simple rule** (no slabs, no dates), audited. There is at most one simple rule per pair. Slab or dated rules for the pair are shown read-only, with a link.
  3. **Copy pricing from another shop.** Copies the price list assignment, special prices and shop-specific rules. The user chooses **Replace** (the target's special prices and shop rules are removed first) or **Add** (on conflicts, the source's special price wins) every time; there is no default. A preview comes first; one audit entry records the copy.
  4. **Bulk price-list change by percentage** for a category (with sub-categories) or brand. It applies only to products already on the list; optionally it also adds the missing ones, starting from the standard price. Rounding is "to the paisa" (default) or "to whole rupees", both half-up via `billing/tax.py`. Preview first; audited like other price changes.
  5. **Shop pricing report:** shops with special prices or shop-specific rules (counts, price list, links), plus the products each shop gets free (ADR-036 item 4). Exportable.
  6. **Excel import/export** through the import framework (ADR-035: explicit mode, change preview, error report):
     - **Special prices:** shop by mobile or code, product code, price, note.
     - **Price-list prices:** list name (an existing list), product code, price.
     - **Discount rules:**
       - Columns: name, target (product code / brand / category, or all), audience (all shops / price list / shop mobile or code), type, value, optional slab quantity, optional valid from and to.
       - The rule **name identifies the rule**; rows with the same name are one rule, one row per slab.
       - In "update existing" mode, a name used by more than one existing rule is a row error.
- **Consequences:** Every tool goes through the pricing services, so audit, validation and the free-goods warning behave the same everywhere. Lists and grids are paginated and priced in batches.

## ADR-038 — Combining discounts
- **Status:** Accepted — 2026-09-26 (product owner). Amends ADR-036 item 1 and PLAN M5.
- **Decision:**
  1. **Setting.** New tenant setting `pricing.discount_combination` ("when several discounts apply"):
     - `BEST` (default, the previous behaviour): the single rule with the largest amount; ties as in PLAN M5.
     - `ADD`: every applicable rule's amount is worked out on the original line (each % of the gross, each flat per unit × quantity), and the amounts are added. For example, 10% + ₹1 off each on a ₹100 unit is ₹11 off.
     - `SEQUENTIAL`: one after another, from the most specific rule to the least. Order: audience (shop, then price list, then all), then scope (product, then deeper category, then brand, then all), newest first on ties. Each % applies to what is left after the earlier rules; a flat rule takes its per-unit amount × quantity from what is left. For example, 10% then 5% is 14.5%.
  2. **Rule values and the cap.** Each rule contributes its reached slab (a rule with slabs and no reached slab does not apply). In every mode the total is capped at the line gross. Rounding follows `billing/tax.py`: each rule's amount is rounded to the paisa.
  3. **The price result lists every rule applied, in order**, with its amount, plus the total. The order line snapshots all of it (Phase 4).
  4. **Shops see only the total discount, as an amount and a percentage of the gross**, for example "You save ₹12 (12%)", in every mode. The percentage is computed by the server to two decimals. Shops never see rule names, how many rules applied, or the price source. "Buy more, pay less" slab hints stay.
  5. `pricing.discounts_on_special_prices` still decides whether any rule applies on top of a special price.
  6. **Free-goods warning.** It checks each rule on its own. Products that several rules make free together show in the shop pricing report (ADR-037 item 5), and they stay hidden from those shops.
- **Consequences:** `resolve_price`'s single `discount` becomes a list of applied discounts plus a total. The tests cover all three modes, with slabs, flat discounts and special prices.

## ADR-039 — Own brand and cost price
- **Status:** Accepted — 2026-09-26 (product owner). Cost visibility amended by ADR-042 (`costs.view` / `costs.manage` instead of the pricing permissions).
- **Decision:**
  1. **Own brand.** A brand can be marked "own brand" (white label). The product list filters by it. Tenant setting `retailers.show_own_brand_badge` (default **off**) shows an "own brand" badge in the shop.
  2. **Cost price.** Products get an optional cost price:
     - Visible only to staff with `pricing.view`; changed only with `pricing.manage`.
     - Omitted from every response otherwise, never in the shop API, and audited on change.
     - Product import/export has a "Cost price" column that needs the pricing permission, as credit columns need the credit permission. Without the permission, the column in a file is refused as an error, not silently ignored.
  3. Margin reports (own brand vs traded) and manufacturing (raw materials, bills of materials, production entries with cost roll-up) are on the PLAN backlog.
- **Consequences:** Staff who manage products but not pricing can still create and edit products; they never see or send cost prices.

## ADR-040 — Responsive design: cards, filter sheet, sticky actions, three checked widths
- **Status:** Accepted — 2026-09-26 (product owner, Phase 2 review).
- **Context:** The shop was mobile-first, but staff and platform screens only avoided sideways scrolling on phones: tables had to be slid sideways, filters took the whole first screen, and some controls were under 44 px.
- **Decision:**
  1. Lists are cards below 1024 px (phones and tablets) and tables above. Each list names its card fields (`title`, `media`, `primary`, `secondary` behind "More", `actions`) instead of stacking every column.
  2. Bulk selection on phones and tablets uses a "Select" mode with checkboxes and a bottom action bar. Laptops keep the checkbox column and inline bar.
  3. On phones, filters live in a bottom sheet behind "Filters (n)", with the search kept visible.
  4. Long forms have Save/Cancel in a bar stuck to the bottom of the screen on phones.
  5. Touch targets are at least 44 × 44 px below 768 px, set in the design-system primitives.
  6. `e2e/responsive.spec.ts` visits every screen at 360, 768 and 1440 px in CI. It fails on sideways scrolling, off-screen or overlapping controls, and phone targets under 44 px, and saves full-page screenshots as the `responsive-screenshots` artifact.
  7. `CLAUDE.md` §6a makes these rules part of the definition of done.
- **Consequences:** New screens reuse `DataTable` (`cardLayout`, `selection`), `FilterBar` and `FormActions`, and are added to the responsive check. The check runs against the full stack after the seed, so it needs the seeded demo records (`manage.py e2e_ids`).

## ADR-041 — Inventory: stock movements, cost method, costs after posting, what shops see
- **Status:** Accepted — 2026-09-26 (product owner, Phase 3 plan). Amends PLAN S8 (valuation) and ADR-039 (cost price). Permissions in items 8 and 9 amended by ADR-042; the opening stock import is one adjustment per file (ADR-042).
- **Context:** Phase 3 adds stock. Own-brand products and a cost price exist (ADR-039), manufacturing is on the backlog, and warehouse staff (no `pricing.view`) receive goods on phones.
- **Decision:**
  1. **One default warehouse per tenant**, created with the tenant (existing tenants backfilled). Every stock row, movement, receipt and adjustment carries the warehouse, so more warehouses can come later behind the existing `multi_warehouse` flag without a data change. A stock level is created with every product (existing products backfilled at 0).
  2. **Stock levels** hold on hand, reserved and backordered quantities in the base unit, with database checks: all three ≥ 0 and reserved ≤ on hand. Available = on hand − reserved.
  3. **Stock movements are append-only** (database trigger; corrections are new movements). Each stores its type, the signed change to on hand and to reserved, both balances afterwards, the unit cost and value where known, the source document (type and id), a reason and the user.
  4. **Movement types are data, not structure.** The type is a string. The direction of each type (which way on hand and reserved move) is one table in `apps/inventory/services.py`, and there is no database constraint listing the types. **Manufacturing** (backlog) adds two types — consume raw material (on hand down) and produce finished goods (on hand up) — as two rows in that table, and a production entry is one more source document. Its movements carry the consumed value, which becomes the finished goods' cost. No table or column changes are needed.
  5. **One write path.** Every stock change goes through one private function inside `transaction.atomic()`. It locks the stock rows with `select_for_update()` in (product, warehouse) order (PLAN §5.1 level L3), applies the change, writes the movement in the same transaction and lets the database checks reject anything negative. Top-level services retry on deadlock.
  6. **Cost is per unit before GST.** Inward cost is entered as "Cost per unit (before GST)": the supplier's GST is input tax credit, not stock value. *Composition-scheme tenants (not supported yet, `tax.registration_type`) cannot claim input credit and would need GST-inclusive cost; that needs a new decision when composition is supported.*
  7. **Cost method** — new tenant setting `stock.cost_method`:
     - `WEIGHTED_AVERAGE` (**default**): posting a receipt line with a cost sets the product's cost price to (stock on hand before × current cost price + received quantity × bill cost) ÷ (stock on hand before + received quantity), rounded half-up to the paisa. If stock before was 0 or less, or the product had no cost price, the bill cost becomes the cost price.
     - `LAST_PURCHASE`: the latest bill cost becomes the cost price.
     - `MANUAL`: receipt costs are recorded but never change the cost price.
     Every automatic change is audited as "updated by GRN-…". Manual edits stay possible in every mode and are audited (ADR-039). Supersedes the per-stock-level `avg_cost` of PLAN S8: the product's cost price is the one cost number.
  8. **Receiving without costs.** Staff without `pricing.view` post receipts with quantities only, so stock is available at once; they never see or send costs. Lines posted without a cost are marked **cost pending**. A user with `pricing.manage` later adds them through a separate, audited **complete costs** action. It never changes quantities or anything else on the posted receipt, and it applies the cost method at that moment (weighted average uses the stock on hand and cost price at completion time). A "Goods receipts awaiting cost" list exists, and its count is shown to users with `pricing.view`. Users with `pricing.view` can enter costs when posting as usual.
  9. **Valuation** is quantity on hand × the product's cost price, with category and brand totals and an Excel export, for users with `reports.stock` **and** `pricing.view`. Products without a cost price are marked, left out of the totals, and counted.
  10. **Reorder level** can be changed by users with `products.manage` or `stock.adjust`; every change is audited.
  11. **Adjustments** cover several products with one reason code and a required note. Each line adds, removes, or records a **counted** quantity (the server works out the difference). Stock that is reserved cannot be removed (`STOCK_RESERVED`). Adjustments are immutable and audited.
  12. **What shops see:** "In stock", "Low stock" (setting `stock.show_low_stock_label`), "Available on backorder" (when backorders are on) or "Out of stock"; the exact quantity only with `stock.show_exact_quantity`. New tenant setting `stock.show_out_of_stock_in_shop` (default **true**): when false, products with nothing available and backorders off are hidden from the shop instead of marked "Out of stock".
  13. **Alerts** (`LOW_STOCK`, `OUT_OF_STOCK`, `BACKORDER_DEMAND`) are evaluated in the same transaction as each stock change. A partial unique index allows one open alert per product, warehouse and type, so each fires once until resolved. Opening and resolving write outbox events (`stock.alert_opened`, `stock.alert_resolved`); notifications deliver them in Phase 6.
  14. **Barcodes:** keyboard-wedge (USB/Bluetooth) and typed barcodes work everywhere, including over the LAN. The phone camera uses the browser's `BarcodeDetector` where available and a scanning library loaded only when the camera opens. Browsers allow the camera only on HTTPS or localhost: over `make lan` it needs a Chrome flag on the phone (documented); real camera testing is on staging.
- **Consequences:** A product's cost price can now change without a manual edit, always with an audit entry naming the receipt. Valuation needs no separate cost history in Phase 3; weighted-average per warehouse, FIFO or batch costing would need a new decision.

## ADR-042 — Cost permissions separate from pricing; one opening-stock document per file
- **Status:** Accepted — 2026-09-26 (product owner, Phase 3 backend checkpoint). Valuation access amended by ADR-043. Amends ADR-039 (who sees and sets the cost price) and ADR-041 items 8–9 and the opening stock import.
- **Context:** Sales staff need `pricing.view` for selling prices, discounts and price lists, but must never see what goods cost the distributor. ADR-039 and ADR-041 tied cost visibility to `pricing.view`.
- **Decision:**
  1. **Two new permission codes.** `costs.view` controls every cost-related field and screen: the product cost price, goods-receipt costs (entered cost, cost per base unit, line and receipt totals), the "Goods receipts awaiting cost" list and count, the unit cost and value of movements, and the valuation report (`reports.stock` + `costs.view`). `costs.manage` (chosen over reusing `pricing.manage`, so changing costs is separate from changing selling prices) is needed to set a cost price, enter costs on a receipt or adjustment, complete pending costs, and import a cost column.
  2. **Default roles:** `costs.view` for Owner, Manager and Accounts; `costs.manage` for Owner and Manager. Not Sales, not Warehouse. Sales keep `pricing.view`.
  3. Without `costs.view` every cost field is null in API responses and cost columns are left out of templates and exports. A test walks every GET route of the tenant API as Sales and as Warehouse, with real ids, and fails if any cost figure in the database appears in any response (JSON, Excel or CSV) or any cost-named field is not null. A control test with Accounts proves the figures are findable.
  4. Receipts can be read with `stock.inward` **or** `costs.view` (so cost staff reach "awaiting cost").
  5. **Opening stock import: one adjustment per file**, with one line per changed row (up to 20,000). The commit re-checks the file: rows that can no longer be applied (for example, stock reserved since validation) are reported with the reason, and the rest are posted together as that one document.
  6. The low-stock report shows how many active products have no reorder level, linking to the stock list filtered to them (`no_reorder_level=true`), where the reorder level can be set.
- **Consequences:** Accounts can see costs and the awaiting-cost list but cannot change costs. The valuation report stays `reports.stock` + `costs.view`, so Accounts (no `reports.stock`) don't see it by default; giving them the report would be a role change, not a code change.

## ADR-043 — Stock value for Accounts; E2E 2FA codes from the backend's clock
- **Status:** Accepted — 2026-09-26 (product owner, Phase 3 final review). Amends ADR-042 item 1 (valuation access).
- **Decision:**
  1. **Stock value report:** `costs.view` **and** (`reports.stock` **or** `reports.financial`). Accounts (costs.view, reports.financial) now sees it; Warehouse (no costs) and Sales (neither report) still don't. Permission requirements can nest (`AllOf(("costs.view", AnyOf(("reports.stock", "reports.financial"))))`); the permission-code and role-matrix tests evaluate them the same way.
  2. **Root cause of the flaky super admin 2FA sign-in in local E2E runs: clock skew, not replay.** The Mac slept for about five minutes during a run (`pmset` log: idle sleep 16:55:04–17:00:06 IST). Docker Desktop's VM was frozen too and its clock synchronises with the Mac only every 30 seconds (`GET /time`: no sync between 16:54:50 and 17:00:21, the VM's monotonic clock advanced 30 s across the gap). A run started right after waking computed the code with the Mac's clock while the backend's clock was still ~5 minutes behind, so the code matched no step in its ±1 window. Replay was ruled out: the helper clears the replay state first, and 30 back-to-back sign-ins passed. CI (Docker on Linux, no VM) is not exposed.
  3. **The E2E helper no longer depends on the machines' clocks or on the reset.** `freshTotp` reads the backend's clock and last used step (`manage.py e2e_totp_state`, dev only), computes the code for the backend's step, waits for the next step when the current one was already used or less than 3 s remain, and a refusal fails at once with its reason (`replay`, `clock skew` with both steps, or `invalid`) and the clock difference.
  4. **The server logs why a code was refused** (`mfa: code refused (replay | clock_skew:±n | invalid)`, without the code). Users still see one neutral message.
- **Consequences:** a slept laptop or a stale container clock can no longer make the E2E suites flaky. Real users are unaffected; the ±1 step window is unchanged.

## ADR-044 — Ordering before billing: credit stub, staff carts, addresses, flaky-network checkout, quick ordering
- **Status:** Accepted — 2026-09-27 (product owner, Phase 4 plan).
- **Context:** Phase 4 adds carts, orders, shipments and backorders, but invoices and the ledger arrive in Phase 5 and message delivery in Phase 6. Shops order from phones on unreliable connections, and ordering must take at most 3 taps from search.
- **Decision:**
  1. **Credit stub until Phase 5.** Exposure = ledger balance (0 until the ledger exists) + value (incl. GST) of every open order quantity **not yet dispatched** + this order. Phase 5 replaces "not yet dispatched" with "not yet invoiced" (the same in the default ON_DISPATCH mode). The fixed formula of ADR-013, the limit semantics and the breach settings apply unchanged. A minimal `ledger.RetailerAccount` row (balance 0) exists from Phase 4 as the per-shop lock (lock order level L1), created with each shop and backfilled.
  2. **No invoice yet.** Dispatch moves the stock (SALE movements) without an invoice; the dispatch step is where Phase 5 issues it. The Order Confirmation is the shop's order page with live updates; its PDF comes with the Phase 5 renderer. Every "retailer is notified" event is written to the outbox now, for Phase 6 to deliver.
  3. **Staff carts.** A salesman ordering for a shop has a separate cart per (shop, staff member); the shop's own cart is never touched. The order records who placed it and how; the shop sees it in the order list and timeline ("Placed by Priya (Sales)").
  4. **Delivery address.** The shop picks one of its saved addresses (default shipping pre-selected); shops cannot add addresses in the app. GST place of supply is the chosen address's state (ADR-010). The checkout note is for delivery instructions (landmark, timing).
  5. **Delivered** is marked by staff with `orders.fulfil` in v1. Shop confirmation of delivery and a one-time delivery code (proof of delivery) are on the backlog.
  6. **Checkout on a flaky connection.** The shop app creates the Idempotency-Key once per checkout attempt and keeps it (across page reloads) until the order succeeds or the cart changes. Every retry after a network failure reuses the key, so no duplicate order can be created. When the outcome of a submission is unknown, the app asks the server about that key (`GET shop/checkout-attempts/{key}`: none, in progress, placed with the order, or failed with the error) before letting the shop try again. An E2E test drops the network during submission and retries.
  7. **Quick ordering.** The quantity stepper and "Add" are on product cards in search results, category lists and "Repeat last order", not only on the product page. The bottom navigation's cart shows the item count. A product in stock can go from search to a placed order in 3 taps (Add, Cart, Place order).
- **Consequences:** Credit limits work in demos before billing exists; nothing about credit changes for shops when Phase 5 arrives in the default invoice mode. Staff and shop never overwrite each other's carts. A double tap, a reload or a dropped connection during checkout can't create two orders.

## ADR-045 — Reductions, credit at allocation, blocked shops, partly delivered
- **Status:** Accepted — 2026-09-28 (product owner, Phase 4 backend checkpoint).
- **Context:** The Phase 4 backend checkpoint raised four questions: which quantity a reduction takes first, how backorders of an order approved over the credit limit are treated, whether manual allocation re-checks credit, and how an order with some shipments delivered and more to come is shown.
- **Decision:**
  1. **Reducing an order before acceptance** takes the waiting (backordered) quantity first, then held stock, so the shop keeps what is ready to send. (A full cancel or reject releases everything either way.)
  2. **Backorders of an order approved from a credit hold.** Approving the hold records the approved value on the order (`credit_approved_value`, its grand total then, backorders included). Allocations for that order are not skipped for the credit limit. Exceptions: (a) under the CURRENT backorder billing price, a price above the order price adds value that wasn't approved, and that extra is checked against the limit as normal; (b) a blocked shop never receives stock, automatically or by hand: it is skipped and flagged (`SKIPPED_BLOCKED`), and confirming an older proposal for it is refused. The queue shows "Approved over limit" and "Shop blocked" on those lines.
  3. **Manual allocation re-checks credit** by the same rules. For a shop over its limit (or taken over it by a higher CURRENT price) it is refused unless the user has `credit.manage` and gives an override reason; the override is audited (`credit.override_applied`) and noted on the allocation. Other users (e.g. Warehouse) see why it's blocked.
  4. **Partly delivered.** While at least one shipment is delivered and something is still to follow (waiting, proposed, or in a shipment not yet delivered), the order's status is PARTLY_DELIVERED ("Partly delivered"), with "N items to follow" (order lines with quantity not yet delivered or cancelled), for shops and staff: in lists, detail, the timeline and the status filter. It replaces the order status DELIVERED. COMPLETED is unchanged.
- **Consequences:** Approving a hold is a real decision about the whole order, and staff never have to approve it twice. Blocked shops can't be sent stock by mistake. Every credit exception at allocation leaves an audit trail. Shops see at a glance that more is coming.

## ADR-046 — Billing before e-invoicing: numbering, documents, returns, salesman collections, ageing, advances
- **Status:** Accepted — 2026-09-28 (product owner, Phase 5 plan). Tax rounding stays pending CA confirmation (ADR-009); the CA review pack is `docs/CA_REVIEW.md`.
- **Context:** Phase 5 adds invoices, credit notes, the ledger, payments and real credit control. E-invoicing and e-way bills come in Phase 7. There is no production data yet; dev databases have Phase 4 shipments dispatched without invoices.
- **Decision:**
  1. **Numbering:** `INV/26-27/000001` for invoices, `CN/26-27/000001` for credit notes, `RCT/26-27/000001` for receipts: prefix, financial year (April–March, IST), 6-digit number, at most 16 characters. The distributor can change a series' prefix (A–Z, 0–9) within that limit. Numbering restarts each financial year and has no gaps (a locked series row inside the issuing transaction).
  2. **Order Confirmation:** when ⚙ `orders.send_confirmation_on_accept` is on, a PDF titled "Order Confirmation" with the line "This is not a tax invoice." is made at acceptance. The shop and staff download it from the order page; Phase 6 sends it.
  3. **Phase 4 shipments without invoices:** a dev-only command (refused unless DEBUG) invoices them dated today, at today's tax rate, in number order, marked as issued after dispatch. `make seed` runs it. Migrations never touch orders.
  4. **Automatic credit notes (ON_ACCEPTANCE timing):** a short pack, a cancelled shipment or a declined higher backorder price issues a credit note automatically (reasons SHORT_SUPPLY / CANCELLATION). It is marked "Issued automatically" in lists and detail, and emits events for Phase 6.
  5. **Returns:** credit notes for returns choose, per line, what happened to the goods: **Return to stock** (default: a RETURN movement, then backorder allocation), **Received damaged** (a RETURN movement then a DAMAGE movement, so the history shows the goods came back and were written off), or **Not physically returned** (value only). Every return credit note needs a reason: damaged, expired, wrong item, excess supply, or other (with a note). Value-only price adjustments need a reason too. Only `invoices.manage` issues credit notes. Shop-initiated return requests are on the backlog.
  6. **Salesman collections:** a new permission `payments.collect` (Sales) lets salesmen record cash, cheque and UPI collections from the shops they can see (⚙ `orders.sales_visibility`). The shop's ledger is credited and a receipt issued at once (cheques follow ⚙ `payments.cheque_credit_timing`). Each such payment is "With salesman" until a user with `payments.record` confirms "Handed over", one by one or in bulk (audited). A "Collections pending handover" report per salesman (count, amount, oldest date) and a dashboard total for `payments.record` users. Setting ⚙ `payments.sales_can_collect` (default on). Recording payments without handover tracking stays with `payments.record` (Owner, Manager, Accounts).
  7. **Invoice copies:** the shop downloads the original; staff print one PDF with three labelled copies (original for recipient, duplicate for transporter, triplicate for supplier). Also a CA question.
  8. **Ageing:** due date = invoice date + the shop's payment terms; overdue = past the due date with a balance. Ageing buckets (0–30, 31–60, 61–90, 90+) count days since the invoice date by default, or days past the due date (⚙ `receivables.ageing_basis`).
  9. **Overdue blocking** (⚙ `credit.block_overdue_after_days`): a shop with any invoice overdue by more than N days is treated as over its limit: new orders are held (reason "Overdue invoices") or blocked per ⚙ `credit.breach_action`; backorder allocation skips and flags it; approving a hold covers that order (ADR-045).
  10. **Advances:** with ⚙ `payments.hold_advances` on, an advance or credit balance is applied to new invoices automatically, oldest money first. A `payments.record` user can reverse an automatic allocation and reallocate it (audited).
  11. **E-invoice readiness:** invoices and credit notes carry `einvoice_status` (NOT_APPLICABLE), `irn`, `ack_no`, `ack_date` and `signed_qr` from Phase 5; the immutability trigger allows only those, payment and PDF columns to change. Phase 7 records point to the document; the PDF shows an IRN/QR block only when an IRN exists.
  12. **PDFs:** HTML templates rendered with WeasyPrint in a background task, stored privately, downloaded through short-lived signed links. The Docker image and CI carry its system libraries and a font with ₹; tests that render real PDFs skip where the libraries are missing.
- **Consequences:** Salesmen can collect without Accounts losing sight of cash in the field; stock history shows every return and write-off; advances never sit unused; nothing about invoices has to change when e-invoicing arrives.


## ADR-047 — Phase 5 checkpoint rules: old bills, payment dates, credit with advances off, refunds, handover
- **Status:** Accepted — 2026-09-28 (product owner, Phase 5 backend checkpoint; item 1's reading of "entries" confirmed and refund reversal added at the final review; item 4's series choice is the lead engineer's).
- **Context:** The backend checkpoint confirmed the overdue, numbering, advances and handover behaviour and asked for these refinements.
- **Decision:**
  1. **Old bills (opening balances).** An opening balance may be several unpaid old bills per shop, one entry each, entered by hand or imported. Each carries its original bill date and a due date (default: bill date + the shop's payment terms; never before the bill date) and an optional old bill number. They age and fall overdue exactly like invoices, and count for overdue blocking. A bill number is accepted once per shop (a database constraint), so a file can't be imported twice by mistake. An opening advance stays once per shop. Import columns: shop, amount (minus for an advance), bill number, bill date (required), due date, note.
  2. **Payment dates.** A receipt's number takes the financial year in which it is recorded. The payment's own date (entered, default today, never in the future) is the ledger entry date — also for a cheque credited only when it clears — and so drives statements, ageing, overdue status and "oldest money first". A payment dated in an earlier financial year than it was recorded is flagged (`dated_in_previous_financial_year`), and the payment form warns before saving (the dues response gives the financial year's start). CA question added.
  3. **Credit with advances off.** When a cheque clears (or a credit note is issued) after the bills are paid, the excess is kept as credit even with ⚙ `payments.hold_advances` off. Staff see "₹X is held as credit even though advances are off" on the payment (`held_as_credit_while_advances_off`) and on the shop's account (`credit_held_while_advances_off`).
  4. **Refunds.** A `payments.record` user can pay a shop back from its credit balance (cash, bank transfer or UPI). A refund debits the ledger, uses the shop's unused money oldest first (it is a target in the allocation engine, like a due that is paid at once), can't exceed the available credit, is audited and prints a refund voucher. It has **its own series, `RFD/26-27/000001`**, so receipts and payments out are never mixed in one sequence. Included in the reconciliation property test. **Reversal (final review, 2026-09-28):** a `payments.record` user can reverse a refund entered in error, with a reason (audited): the money it used goes back to the shop's credit (and pays what the shop owes, oldest first), a REFUND_REVERSAL credit points at the original entry, the refund shows "Reversed", and the voucher is printed again marked "Reversed". Also in the reconciliation property test.
  5. **Handover follows the money.** A collection reversed as entered in error leaves the pending-handover list ("Nothing to hand over"); the reversal is audited with that fact. A cheque still "With salesman" that bounces is first recorded as handed over, automatically, with an audit entry naming the user. The pending-handover report and totals count only money actually with salesmen.
  6. **Who recorded a payment** (staff name) is shown to the shop.
- **Consequences:** Old dues age from their real dates; statements read in date order whatever the recording order; the office always knows where the cash is; a shop's credit can leave the business only through a numbered, audited refund.

## ADR-048 — Notifications: rules, channels, WhatsApp consent, secure document links, quiet hours, reminders
- **Status:** Accepted — 2026-09-29 (product owner, Phase 6 plan).
- **Context:** Phases 3–5 write domain events to the outbox (orders, backorders, stock alerts, invoices, credit notes, payments, refunds). Phase 6 delivers them. WhatsApp costs money per message and needs the shop's consent; shop owners are not technical and mostly use WhatsApp.
- **Decision:**
  1. **Pipeline.** One outbox consumer (`notifications.dispatch_event`) handles every notifiable event type. It resolves the tenant's rules (platform defaults, overridden per tenant), finds the recipients and writes one `Notification` per recipient and channel. The unique key (event, recipient, channel) makes a replayed event a no-op. Each notification is delivered by its own Celery task, retried up to 5 times with exponential backoff; every try is a `DeliveryAttempt` (provider, response, error, duration). Failures are listed for the distributor (`notifications.manage`, with manual retry) and across tenants for the super admin.
  2. **Recipients** are resolved by rule: the shop (its login, mobile and email), the shop's salesperson, the salesman who collected a payment, staff holding a given permission (so custom roles keep working), and owners.
  3. **Channels.** In-app (notification centre with a live badge, for staff and shops), email (mock in dev/test, Amazon SES adapter for production; sent from the platform address with the distributor's name, replies to the distributor's email), WhatsApp (mock + adapter interface; gated by the `whatsapp` feature flag), SMS (sign-in codes and the shop welcome only). Every provider sits behind an adapter; dev and test use mocks only and deployed settings refuse mocks.
  4. **WhatsApp identity.** One platform number for now. A `WhatsAppSender` row per tenant (encrypted credentials) can later connect the distributor's own number; sending looks up the tenant's active sender and falls back to the platform's. Every WhatsApp template names the distributor in the body ("Sharma Distributors: your order ORD-… was accepted"). The provider is undecided: interface and mock only, with a `TODO(verify)`; the pre-production checklist asks the provider to confirm one number may send for several businesses, and how incoming "STOP" replies are handled.
  5. **WhatsApp consent.** Each shop has an opt-in status with timestamp and source: the shop in the app (a one-time prompt after sign-in, and a switch in its notification settings), staff when adding or editing the shop (with a confirmation checkbox), or an import column (source "import"). No WhatsApp message goes to a shop without opt-in, compulsory events included (they still go in-app and by email). Opting out is always possible and stops WhatsApp at once. The rules screen shows how many shops have opted in. Changes are audited.
  6. **Default rules** (PLAN §10.2h has the full table): order, backorder, billing and payment events go to the shop in-app and, where it matters, by WhatsApp; invoices, credit notes and receipts also by email to shops with an address. With invoicing at dispatch, the invoice's WhatsApp message covers the dispatch ("on its way", bill amount, PDF link) and `order.dispatched` is in-app only; `order.accepted` carries the Order Confirmation link. Staff get in-app (and email for credit holds and GST warnings).
  7. **Compulsory events.** Each shop rule has a "compulsory" flag set by the distributor; by default `invoice.issued`, `credit_note.issued`, `payment.reversed` (bounced cheque) and `payment.reminder`. Shops can't switch off channels of compulsory events; they can for everything else. In-app can never be switched off.
  8. **Secure document links.** Invoices, credit notes, receipts, refund vouchers and the Order Confirmation are sent as a link that opens without signing in: an opaque random token (stored hashed) for one document, valid ⚙ `notifications.document_link_days` (default 30). Opening it redirects to a fresh 5-minute storage link to the current PDF (so a reversed refund or bounced receipt shows the updated document); each open is counted. Staff with the document's manage permission can revoke a document's links (audited).
  9. **Urgency and quiet hours.** Each event is transactional (sent at once) or non-urgent: payment and handover reminders, stock alerts, GST rate warnings, announcements. Non-urgent WhatsApp, SMS and email wait during ⚙ quiet hours (default 21:00–08:00 IST) and go out when they end; in-app is never held.
  10. **Payment reminders.** A daily job sends each shop one message listing its overdue bills and total with a statement link, on ⚙ `notifications.payment_reminder_days` (default: 2 days before the due date, then 3, 7, 15 and 30 days overdue) and then every ⚙ `notifications.payment_reminder_repeat_days` (default 15). Compulsory; shops can't switch it off. Staff with `credit.manage` can pause reminders for a shop, with a reason and an optional end date (audited).
  11. **Handover reminders.** Daily at 09:00: collections "with salesman" for more than ⚙ `notifications.handover_reminder_days` (default 2) — a digest to the salesman (in-app + WhatsApp) and to staff with `payments.record` (in-app). Handing over writes a `payment.handed_over` event.
  12. **GST rate-change warning** (ADR-022): a daily job emits `tax.rate_change_upcoming` 7 days before a product's GST rate changes, listing the affected products (staff with `products.manage`: in-app + email), and the dashboard shows the card.
  13. **Cost estimate.** Platform settings hold a WhatsApp price per message category (utility, marketing, authentication), empty until the super admin sets them. Each event's WhatsApp template has a category (order, billing, payment and reminder messages are utility; announcements are marketing). The rules screen estimates each WhatsApp-enabled event's monthly messages from the last 30 days and prices them with its category's price; it shows counts only while prices are unset.
  14. **Templates.** Platform defaults in English per event and channel, with tenant overrides and a preview. Rendering is sandboxed (only the event's known variables, no template tags beyond plain substitution). WhatsApp templates store the approved template name, language, category and ordered variables. A shop's preferred language is used when a template exists in it, else English.
  15. **Shop welcome and staff emails.** The shop welcome SMS moves into the service (logged, retryable, not switchable). Staff invitation and password-reset emails stay outside the rules (always sent) but use the same email adapter.
  16. **Announcements.** The distributor posts notices shown on the shop home (dates, active flag), optionally also sent by WhatsApp (marketing category).
- **Backend checkpoint (2026-09-29, product owner):**
  1. Pausing a shop's payment reminders stops every channel, in-app included. The shop's outstanding and overdue amounts still show on its home and bills pages (pausing touches only the messages).
  2. Only the super admin edits WhatsApp and SMS texts (approved templates); distributors edit in-app and email texts. Backlog: a distributor with its own WhatsApp number manages its own templates.
  3. Payment reminders cover bills due soon as well as overdue ones ("2 bills to pay, … (… overdue since …)").
  4. The bounced-cheque WhatsApp carries no link; it names the cheque number and date, the amount and the shop's new balance. The receipt link sent earlier opens the receipt printed again as "Cheque bounced". Backlog: an optional cheque bounce charge.
  5. Expired or revoked document links answer 410 with a short page ("ask {distributor} for a new link").
  6. Notification settings are edited with `settings.manage`, like every setting.
  7. A shop's WhatsApp, SMS and email go once to the shop's own number and address; each login gets in-app.
- **Final review (2026-09-29, product owner): texts per audience.** A text is chosen by event, channel and audience: the shop's words ("Your order ORD-… for ₹… has been placed.") for a shop's logins, the office's words ("Ganesh Kirana placed order …") for staff. Every event a shop can receive has both (the welcome message and announcements go to shops only; staff-only events have the office's words only), so a message never reaches someone in the other audience's words. The rules accept a channel only if it has a text in the recipient's words; secure document links appear only in the shop's words. The distributor's text editor and the super admin's defaults show both audiences; the office's approved WhatsApp templates end in "_staff".
- **WhatsApp submission (2026-09-29, product owner):** staff rely on in-app and email; the default rules send staff WhatsApp only for the salesman's handover reminder. The first batch submitted for approval is the 26 shop templates plus the handover reminder; the other staff templates are optional and not submitted by default (marked so on the super admin's screen). If a distributor turns on staff WhatsApp for another message before its template is approved, the provider refuses it and the delivery log shows it failed. Production email stays on the SES adapter.
- **Consequences:** Nothing is sent twice; every message is traceable; WhatsApp spend is visible before it is enabled and never reaches a shop without consent; night-time messages are limited to what the shop just did.

---

## ADR-049 — E-invoicing, e-way bills and online payments, behind flags that change nothing when off
- **Status:** Accepted — 2026-09-29 (product owner, Phase 7 plan).
- **Context:** Invoices, credit notes and the PDF have carried empty e-invoice fields since Phase 5 (ADR-046 item 11). Distributors above the e-invoicing threshold must report B2B invoices to the Invoice Registration Portal (IRP) through a GST provider (GSP); goods above a value need an e-way bill; shops want to pay online. No GSP is chosen; Razorpay is the first gateway. Several GST rules must be checked against current official sources before production.
- **Decision:**
  1. **Flags.** `einvoice`, `ewaybill` and `payments` stay default-off and are switched on per distributor by the super admin only. A module works only when its flag is on **and** the distributor's credentials are saved and verified (the owner, `settings.manage`, enters them; stored encrypted, masked on read). With every flag off the app behaves exactly as before Phase 7: a baseline snapshot of a full flow (order → acceptance → dispatch → invoice → payment → credit note: documents, ledger, allocations, outbox events, notifications, PDF HTML) is taken before any Phase 7 code and must stay identical.
  2. **Rules not taken as fact.** Every GST rule the code depends on (thresholds, reporting limits, windows, Part-B, state variations) is a setting or a labelled placeholder and is listed on the pre-production checklist (PROGRESS items 10–25) until verified against current official sources. Current understanding (₹5 crore for e-invoicing, ₹10 crore and 30 days for the IRN reporting limit) is kept as platform settings.
  3. **Turnover band.** A distributor setting "annual turnover band" (below ₹5 crore / ₹5–10 crore / ₹10 crore and above), editable by the owner and the super admin, audited. It drives suggestions and warnings only: e-invoicing is suggested from the platform's e-invoicing threshold band; the reporting-limit warning appears only for the band at or above the platform's reporting-limit threshold. The flag alone decides whether e-invoicing runs.
  4. **GST provider.** A `compliance` app with an adapter interface and a thorough mock. We build a neutral e-invoice document from the invoice or credit note's snapshots; mapping it to a provider's payload is the real adapter's job and is left as marked `TODO(verify)` until a GSP is chosen. We do not guess any provider's field names. The mock is deterministic and simulates success, duplicate IRN (returning the existing IRN), invalid GSTIN, validation errors, the portal down and timeouts; in dev a setting can force any of these. Duplicate checks compare document numbers case-insensitively (ours are uppercase already; the IRP is understood to treat them case-insensitively, to verify).
  5. **Which documents.** IRNs for B2B invoices (the shop has a GSTIN) and their credit notes only; none for B2C. Generated automatically when the invoice is issued (⚙ `einvoice.auto_generate`, default on; a "Generate IRN" button otherwise), in the background with retries. The invoice shows Pending, Generated or Failed with the reason; a permanent failure leaves the invoice valid and marked "IRN failed" for staff to fix (e.g. the shop's GSTIN) and retry. Staff with `compliance.manage` are told of failures; the dashboard counts pending IRNs; a warning appears as a pending or failed IRN nears the reporting limit (⚙ platform, placeholder 30 days; only for the ₹10 crore+ band).
  6. **The PDF** is printed again with the IRN, acknowledgement and the signed QR code (rendered with `segno`) once the IRN arrives. The shop's bill message (in-app, WhatsApp, email) waits until the IRN is generated or has failed, at most 10 minutes, so the shop's first copy carries the QR; document links always open the latest PDF.
  7. **IRN cancellation** within the permitted window (placeholder, to verify), with a reason code, audited; outside the window, corrections are by credit note only, as today. At cancellation staff choose what happens to the goods: **(a) re-issue a corrected invoice with a new number for the same shipment (default; the goods stay with the shop)**, or (b) take the goods back (stock returns; the quantities go back on backorder or are cancelled). Either way the cancelled invoice keeps its number, its ledger debit is reversed and its allocations are undone (the money becomes the shop's credit and is applied again, oldest first).
  8. **E-way bills** are generated from the invoice at dispatch when eligible (the consignment value above ⚙ thresholds, one for moves between states and one within the state, both placeholder ₹50,000 until verified). Dispatch never waits for the e-way bill: a failure shows prominently with generate and retry. The distance is stored per shop address and editable at dispatch. Part-B updates and cancellations are recorded append-only; the e-way bill number is printed on the invoice.
  9. **Online payments.** Each distributor connects its own Razorpay account (keys and webhook secret encrypted); money settles to the distributor, never to the platform. The shop pays a bill (its full balance), everything it owes, or a custom amount (at least ₹1; capped at what it owes when advances are off, as offline); no surcharge (the distributor bears gateway fees; a convenience fee is on the backlog). A payment is confirmed **only** by a signature-verified webhook (stored, deduplicated by event id) or by the reconciliation job asking the gateway (every 15 minutes); the client's callback is informational. A captured payment goes through the existing flow: ledger credit dated on capture, allocation (that bill first, then the oldest dues), an RCT receipt, the "payment received" message; it is recorded as paid online by the shop's login. A captured amount that differs from the checkout is recorded as paid, allocated normally and flagged for staff; if advances are off and it exceeds what is owed, the excess is kept as credit with the same "held as credit" notice as cheques. Staff with `payments.reverse` can reverse an online payment entered in error (e.g. a chargeback), with a reason, audited, without calling the gateway; gateway refunds are out of scope (refunds stay offline).
  10. **One active checkout.** A shop has at most one active checkout per bill, per "pay everything" and per custom amount at a time: a second tap or tab reuses it instead of creating another gateway order, and a stale checkout expires before a new one starts (enforced by a database constraint; concurrency-tested).
  11. **Razorpay** through its official Python SDK. Every request field, event name, header and payload path is marked `TODO(verify)` against Razorpay's official documentation and listed on the checklist. In dev and tests a mock gateway (with a mock checkout page that sends a correctly signed mock webhook) replaces it; deployed settings refuse the mock.
  12. **WhatsApp template approval (Phase 6 carry-over).** Each platform WhatsApp template has an approval status (not submitted, submitted, approved, rejected) set by the super admin. The rules editor offers WhatsApp only when the template in the recipient's words is approved and says why otherwise; existing rules using an unapproved template show a warning, and such messages are skipped with the reason "Template not approved" (in-app and email still go). With the mock provider (dev, tests) every template counts as approved.
- **Consequences:** Distributors below the thresholds, or not ready, see no change. Every call to the IRP, the e-way bill system or the gateway is retried in the background and never blocks issuing, dispatching or recording. Nothing reaches a real GSP or gateway until the pre-production checks are done and a GSP is chosen.
- **Implementation notes (backend, 2026-09-30):**
  - *Flags off, nothing new:* settings of an off module are left out of the settings screen and refused (`MODULE_NOT_ENABLED`); notification events of an off module (`einvoice.failed`, `invoice.cancelled`) are hidden from the rules, texts and preferences; the new API fields are null or false. The turnover band is therefore set by the owner only while a compliance module is on; the super admin can set it at any time.
  - *Cancelled invoices:* the reversing ledger entry credits the whole invoice, so it owes nothing and drops out of the dues (its running columns say "credited in full"); payments matched to it are freed and settle onto what the shop owes, the re-issued invoice included. An invoice with credit notes, or with a live e-way bill, can't have its IRN cancelled (correct it with a credit note / cancel the e-way bill first). Only invoices' IRNs are cancelled here; a credit note's is not offered. The re-issued invoice uses the order and the shop's current details and today's rates; it gets its own IRN but no e-way bill automatically (staff can make one).
  - *Taking goods back* returns the stock (a RETURN movement), puts the quantities back on order or cancels them, cancels the shipment and reopens a completed order; returned stock may at once be held for waiting orders (a backorder proposal).
  - *The shop's bill message* holds WhatsApp and email for the IRN (at most 10 minutes); in-app shows at once. The shop is told in the app when a bill is cancelled; its email and WhatsApp texts exist but are off by default, and the WhatsApp template is optional (not in the first submission batch).
  - *External calls:* IRN, e-way bill, credential and gateway checks and reconciliation run in the background with no transaction held. Two calls run while a person waits, by necessity: the gateway order when a shop taps Pay (serialised per shop; a gateway that doesn't answer leaves nothing behind), and asking the gateway whether a stale checkout was paid before replacing it.
  - *E-way bills* allow one change (a new vehicle or a cancellation) at a time; a typed distance is kept on a shop address that had none.
  - *Online payments* are recorded by the shop's login that paid; a second capture on an already paid checkout is recorded and flagged; a failed try keeps the checkout open for another try.
- **Backend checkpoint answers (product owner, 2026-09-30):** the implementation notes above are approved (turnover band, bill message hold, cancellation limits, cancelled invoice, taking goods back, e-way bills for unregistered shops to verify, checkout timing, online payment records, live keys only in production, approval reset on edit), with these changes:
  1. A refused IRN cancellation says what to do first ("Cancel e-way bill 1234… first, then cancel the IRN"; "…because credit note CN/… was issued against it. Correct the invoice with another credit note instead."); the invoice's e-invoice summary carries the reason (`cancel_blocked`).
  2. A re-issued invoice uses the shop's **current** details (name, GSTIN, addresses; the place of supply follows its delivery address) but the **original** quantities, prices, discounts, GST rates and rounding of the cancelled invoice. When a line's GST rate valid today differs, staff see it (`reissue-preview`) and must confirm. CA question 30 asks which rates are right.
  3. "Bill cancelled" goes to the shop in-app and by email by default, naming and linking the new bill when re-issued; WhatsApp stays optional.
  4. A failed e-way bill is notified at once (urgent, not held for quiet hours), in-app and by email, to staff who manage compliance and to the person who dispatched the shipment (a new recipient, "The person who dispatched", offered only for this message and only while e-way bills are on); it names the shipment, vehicle and error and links to retry; the dashboard shows failed e-way bills until resolved.
  5. The two calls the shop waits on stop after 10 seconds and are never retried there; the shop sees "Payment service is busy, please try again in a minute."; a stale checkout is never replaced while the gateway can't say whether it was paid.

## ADR-050 — Dashboards and reports: one report framework, permissions built in, heavy exports in the background
- **Status:** Accepted — 2026-09-30 (product owner, Phase 8 plan).
- **Context:** Distributors open the panel to see what needs action and to pull the reports they use every day (sales, stock, dues, collections, GST for filing). A few reports exist (low stock, valuation, receivables ageing, collections pending handover), each built on its own; nothing runs in the background, and the super admin dashboard only counts distributors. Reports must respect every permission already in place, stay fast on a large distributor (section 7: p95 under 300 ms), and give a CA what they need for GST filing. No CA is engaged yet (one will review everything before launch), so tax-facing layouts follow official sources and every open point goes to `docs/CA_REVIEW.md` and the pre-production checklist without blocking work.
- **Decision:**
  1. **One report framework** (`apps/reports`). Each report is a definition: code, title, group, the permission rule, filters (validated; bounded date ranges), columns (some marked *cost*), totals, the row query and a default sort. The API lists the reports a user may open, returns a page of rows with totals, and exports. Views never build queries.
  2. **Permissions built in.** A report is offered and served only with its permission: `reports.sales` (all shops) or `reports.sales_own` (own shops), `reports.stock`, `reports.financial`. Cost and margin columns and the margin report need `costs.view` as well; without it cost columns are left out of rows, totals and exports, never just hidden. When `orders.sales_visibility = ASSIGNED_RETAILERS`, a user who sees own shops only (the existing rule) gets rows of shops assigned to them, in every report and export. Receivables ageing and salesperson collections are open to `reports.financial` (all) and `reports.sales_own` (own shops).
  3. **Sales** are invoices by invoice date minus credit notes by note date, with taxable value, GST and total. Invoices whose IRN was cancelled are excluded; their re-issues count. The dashboard shows both **"Orders received"** (orders placed, by order date, including GST) and **"Billed"** (this definition), since they differ when invoicing happens at dispatch.
  4. **Salesperson on each order.** An order records the shop's salesperson when it is placed (`Order.salesperson`); sales by salesperson use it. Orders placed before Phase 8 take the shop's salesperson at migration time.
  5. **Margin cost.** An invoice line records the product's cost price when the invoice is issued (`InvoiceLine.unit_cost`, per base unit, before GST). Margin = taxable value − quantity × unit cost, returns taken off at the invoice line's cost. Lines issued before Phase 8 (or of products without a cost) use today's cost price and are marked **"estimated"**; lines with no cost at all are shown apart and left out of margin totals. Own brand vs traded follows the product's brand (ADR-039).
  6. **Fast / slow / dead stock** over ⚙ `reports.movement_days` (default 90): products ranked by sales value by default (a switch ranks by quantity); **fast** = the top ⚙ `reports.fast_share_percent` (default 20) of products that sold, **slow** = the rest that sold, **dead** = in stock and nothing sold, **new** = first stocked within the period and nothing sold yet (never called dead).
  7. **Fulfilment rate**, by order date: by quantity (delivered ÷ ordered, leaving out quantities the shop cancelled) and by order (orders delivered in full).
  8. **Salesperson collections**: money each salesperson collected themselves (cash, cheque, UPI) with its handover status, and a column for everything received from their shops by any means.
  9. **GST summaries for filing.** A workbook for a month or a quarter (QRMP filers), laid out like the official GSTR-1 Excel template: B2B invoice-wise, B2C large (inter-state to unregistered above ⚙ platform `platform.b2cl_threshold`, currently ₹1 lakh), B2C others (by rate and place of supply), credit notes to registered and unregistered buyers, the HSN summary in separate B2B and B2C tabs (HSN, description, UQC, quantity, values and taxes by rate), and documents issued (series ranges; cancelled invoices counted as cancelled and left out of the other sections). Sheets and columns are copied from the official template when it is implemented, never guessed; thresholds are platform settings; everything is marked to verify and asked of the CA. The portal's JSON upload is later, after CA review.
  10. **Exports.** Every report exports to Excel; the sales summary, receivables ageing, collections and the GST summary also to PDF. An export of more than ⚙ platform `platform.report_async_rows` (5,000) rows, and every GST workbook, runs in the background on its own worker queue (`reports`, so it never delays messages or IRNs); the requester gets an in-app "Report ready" message and a download link valid ⚙ platform `platform.report_link_days` (7) days; files are deleted after that. A `ReportRun` records each export (who, which report, filters, rows, status, file).
  11. **Distributor dashboard**, one endpoint, each part only with its permission: first **what needs action today** (new orders, holds, backorders to confirm, failed IRNs and e-way bills, collections pending handover, overdue receivables, low and out-of-stock products), then **today's** "Orders received" and "Billed", then **trends**: billed sales per day for the last 30 days against the 30 days before, the top 5 products and top 5 shops this month, new vs repeat shops. Charts use `recharts` (the library shadcn's chart components build on).
  12. **Super admin dashboard** through the audited cross-distributor path (`platform_db`): active distributors, orders per day (count and value including GST), failed messages and compliance errors per distributor, and usage against plans (shops, staff, products vs the plan's limits, shown even while enforcement is off).
  13. **Performance.** A volume seed creates 50,000 orders across three test distributors (40,000 / 5,000 / 5,000) with invoices, credit notes, payments, stock movements and ledger entries that reconcile. `make perf` measures the dashboard and the first page of every report (default range: this month) against p95 < 300 ms; longer ranges become background exports. Indexes come first; summary tables (e.g. daily sales per product and shop) only where measurement needs them; each is documented with its measurement. *Built (backend checkpoint, 2026-09-30):* the seed simulates the year in time order and bulk-inserts it, with the services' tax arithmetic, numbering, ledger postings, oldest-due-first matching and stock movements, and refuses to commit unless `reconcile()` finds everything consistent; through the services it would take over three hours (232 ms per order placed, accepted, packed, dispatched, invoiced and paid). Measured: every page's p95 ≤ 193 ms for the owner of the 40,000-order distributor. No index or summary table was needed; three query changes were (PROGRESS, Phase 8 item 9). *Exports (product owner, 2026-10-01):* background exports read rows in chunks, write the file to a temporary file and upload it in parts, so memory stays flat whatever the size; `make perf-exports` measures the heaviest ones (the full-year sales register, a GSTR-1 quarter, 92 days of stock movements) against 2 minutes each. The sales register (**Sales by invoice**: every invoice and credit note, one per row, credit notes as minus amounts) was added then.
  14. **Out of scope** (backlog): the accounting export for Tally (designed here, item 15; built once someone can test a real import), saved filters and scheduled email reports (the browser remembers each person's last filters), a daily morning summary for owners, and the GSTR-1 JSON upload.
  15. **Tally export design** (backlog until a real TallyPrime import can be tested). TallyPrime imports transactions from XML (Import → Transactions; dates as YYYYMMDD) and from Excel through its sample templates; its documentation says third-party files should match what TallyPrime itself exports for the same voucher. The export: one XML file per period with **Sales** vouchers (our invoices), **Credit Note** vouchers and **Receipt** vouchers as accounting entries without stock items, our document number as the voucher number, bill references (new reference on invoices; against the invoice on credit notes and receipts), and optional party-ledger masters (shop name, GSTIN, state, address) for import first. A **ledger-name mapping** page (owner) names the distributor's Tally ledgers: party ledger per shop (default the shop's name), sales ledger (one, or one per GST rate), output CGST / SGST / IGST / cess ledgers, round-off, and the cash and bank ledgers per payment mode; voucher type names are editable. Cancelled invoices, re-imports of the same period and the amount sign convention are settled from a sample voucher exported from the CA's TallyPrime. The export is labelled **beta** until a real import succeeds.
- **Consequences:** Every report follows the same permission, scope and export rules, tested once in the framework and per report for isolation. Past sales keep their salesperson and cost from Phase 8 on; earlier ones are marked estimated or use the shop's salesperson at migration. GST and Tally layouts wait on official templates and a CA; the app keeps working with the current defaults meanwhile.

## ADR-051 — PostgreSQL JIT off for the app's connections; product details looked up per line in sales reports
- **Status:** Accepted — 2026-10-01 (lead engineer, Phase 8 final review: the cost-visible sales reports' scan, until then a known issue).
- **Context:** For someone who sees costs, the sales reports joined each invoice line's product for today's cost price (and for its category, brand or own-brand flag). That join makes PostgreSQL misjudge how many lines match, so it read every line of the distributor (172,000 at vol-a) instead of the period's (18,000). Looking the product up per line instead lets it start from the period's invoices (index on tenant and date), but the lookups raise the query's estimated cost past PostgreSQL's JIT thresholds. It then compiled the query to machine code first: a month's sales by product took 396 ms with JIT and 18 ms without, the plan's own work being 5 ms.
- **Decision:**
  1. Every database connection the app opens turns JIT off (`-c jit=off` in the connection options of every alias, `config/settings/base.py`). JIT pays off on long analytical scans; the app's queries are short page loads and chunked exports, where the compile time dominates.
  2. The sales reports look the product's cost price, category, brand and own-brand flag up per line (`product_value`) rather than joining products. Own brand vs traded folds the per-product figures in Python (one grouped query and a small lookup), instead of grouping every line by its brand.
- **Consequences:** At 40,000 orders a year, for an owner over a whole month, the sales reports take 55-102 ms p95 (106-171 before) and own brand vs traded 61 ms; nothing in the app needs JIT. A future long analytical query that would benefit can switch it on for its own transaction (`SET LOCAL jit = on`). A connection pooler in transaction mode (e.g. PgBouncer) drops connection options; if one is added, set the default on the database roles instead (`ALTER ROLE app_user SET jit = off`, and likewise for the platform role).

## ADR-052 — Health endpoints answer any host over plain HTTP
- **Status:** Accepted — 2026-10-01 (lead engineer, Phase 8 final review).
- **Context:** Load balancers and orchestrators probe a container by its address over plain HTTP. Django refuses an unknown host (`ALLOWED_HOSTS`, 400) and production redirects plain HTTP to HTTPS (301), so such a probe would have marked a healthy backend unhealthy. In development, Docker's own check calls `localhost`, which LAN mode (`make lan`) doesn't allow, so the backend showed as unhealthy there.
- **Decision:** `common.health.HealthCheckMiddleware`, first in `MIDDLEWARE`, answers GET `/health/live` (the process is up) and `/health/ready` (database and cache answer; 503 otherwise) for any host and over plain HTTP, before host validation, the HTTPS redirect and the request context. Every other request, and anything but GET on these paths, goes through as before. The production image has a Docker `HEALTHCHECK` on `/health/live`. CI starts the production image with production settings and requires a probe by IP to get 200 from `/health/live`, 400 from the API and Docker to report healthy.
- **Consequences:** Probes need no host header or TLS. The endpoints are reachable by any host, but they were public already and only say whether the app is up. Health requests carry no request id and aren't counted in the error rate (they weren't before either).

## ADR-053 — Phase 9 split; Phase 9a: global search, stock planning and purchasing
- **Status:** Accepted — 2026-10-01 (product owner: the Phase 9 split, then the Phase 9a plan with answers 1–14 and global search).
- **Context:** Phase 9 in the spec (smart inventory and AI, plus optional modules) and the PLAN backlog had grown too large for one phase. The owner wants a pilot distributor on a real HTTPS staging environment while the rest is built, and each part independently mergeable, so AI (9d, 9e) and free-goods schemes can move after launch if time is short.
- **Decision:**
  1. **The split.** 9a stock planning and purchasing (with global search); **9a+ staging** on AWS Mumbai (infrastructure as code, a CI deploy from `main`, sandbox providers only, a test-environment banner, a pilot-ready seed, a runbook; prepared in full if the AWS account or domain isn't ready, without blocking 9b); 9b sales growth (re-engagement insights, daily owner summary, free-goods schemes); 9c shop self-service and money (delivery confirmation and code, return requests, cheque bounce charge); 9d AI foundation and semantic search; 9e distributor data assistant. Phase 10 also gets the Platform Support role, and the Tally export and GSTR-1 JSON during the CA review. **After launch:** multi-warehouse and transfers, batches and expiry (earlier if a pilot needs expiry tracking), manufacturing, demand forecasting, supplier-bill photo reading, convenience fee, the distributor's own WhatsApp number and templates, saved filters and scheduled reports. Each sub-phase is its own branch and PR.
  2. **Global search** (core, never behind a flag). One bar in the distributor panel and the super admin area: Ctrl/Cmd+K on laptops, a search icon opening a full-screen search on phones; results as you type (debounced), arrows, Enter and Esc, and the person's recent searches (kept in that browser, per person, like the remembered report filters).
     - Distributor: products (name, code, barcode), shops (name, owner, mobile, GSTIN), orders, invoices, credit notes, receipts and payments (number, reference, cheque number), refunds, goods receipts, adjustments, staff, suppliers and purchase orders; pages and settings by name.
     - Super admin: distributors (name, legal name, GSTIN, web address) and platform pages and settings; users across distributors only through the audited platform path.
     - Smart matching: a document number (`ORD-`, `INV/`, `CN/`, `RCT/`, `RFD/`, `GRN-`, `PO-`), a GSTIN or a 10-digit mobile jumps straight to its match; otherwise ranked results grouped by type, with the existing full-text and trigram search.
     - Every result type needs its own view permission; the sales-visibility rule limits shops and their documents; tenant isolation as everywhere; results never carry cost data. Records come from the server; pages and settings are matched in the browser from the translated names (the server still guards every page). The bar is built so 9e can add "Ask the assistant".
  3. **Product stats** (flag `stock_planning`), nightly per distributor and on demand: daily demand (quantity ordered in ⚙ `planning.demand_days`, 30, shop cancellations and rejected orders left out), days of stock left, last sale, ABC class (by sales value over ⚙ `reports.movement_days`: A the products making ⚙ `planning.abc_a_percent` 80% of value, B up to ⚙ `planning.abc_b_percent` 95%, C the rest, none if nothing sold) and the fast / slow / dead / new class, with the Phase 8 report's definitions.
  4. **Suppliers** (flag `purchasing`): name, GSTIN, state, contact, phone, email, address, payment terms, default lead time, notes; an Excel import. A product can have several suppliers, one preferred, each with its own code, lead time and pack. Past goods receipts' free-text supplier names become suppliers only through a one-time list staff review and confirm.
  5. **Purchase orders:** Draft → Sent → Partly received → Received, or Closed (the rest cancelled, with a reason) or Cancelled; `PO-2026-00001`. Cost per unit before GST, with GST estimated from the product's rate and the supplier's state for information only; no purchase accounting. A PDF on the distributor's letterhead; Send emails it to the supplier (a new email-only recipient, the text editable like others, logged and retried) and gives a share link for WhatsApp from staff phones. Editable and re-sent (marked revised) until something is received; after that only "close the rest" or cancel. Cancelling a sent order emails the supplier too (editable text, the cancelled copy linked), with a "don't email the supplier" choice when staff have told them already (product owner, backend checkpoint).
  6. **Receiving against a purchase order** makes a goods-receipt draft with what is still due and the order's costs, so staff who can't see costs receive with no "cost pending". More than ordered is accepted with a warning up to ⚙ `purchasing.over_receipt_tolerance_percent` (10%); above it, posting needs a user with `purchasing.manage` to confirm (audited).
  7. **On order:** anyone with `orders.view` or `stock.view` (sales staff too) sees a product's quantity on order and expected arrival on the product page, the backorder screens and a shop's order as staff see it, without supplier names or prices.
  8. **Reorder suggestions** (flag `stock_planning`; with `purchasing` also "on order" and "Create purchase order"): daily demand d; position = available + on order − waiting on backorder; reorder point = d × lead time + safety stock (⚙ `planning.safety_days`, 7, of demand); when the position is at or below it, order d × (lead time + ⚙ `planning.cover_days`, 14) + safety stock − position, rounded up to the supplier's pack. Lead time: the product's supplier, else the supplier's default, else ⚙ `planning.default_lead_days` (7). Little or no history: only when shops are waiting or stock is at or below the manual reorder level, ordering up to that level plus what is waiting. Each suggestion's figures come from the server and the app words them ("Sold 120 in the last 30 days (4 a day) …"). Staff change the quantity, dismiss, use the reorder point as the product's reorder level (one or in bulk, audited; never automatic) or create purchase orders, grouped by preferred supplier.
  9. **Flags and permissions.** New flags `purchasing` and `stock_planning`; `ai` now covers only smart search and the assistant. New codes `purchasing.view` (owner, manager, warehouse, accounts) and `purchasing.manage` (owner, manager); receiving stays `stock.inward`; prices on purchase orders only with `costs.view`; stats and suggestions with `purchasing.view` or `stock.view`.
  10. **Around it:** dashboard tiles "Products to reorder" and "Purchase orders late"; a Purchases by supplier report; "On order" and "Expected" on the backorder demand report; a Stock planning settings group.
- **Consequences:** The pilot gets search and purchasing first. Purchasing never touches the ledger, and stock still changes only through goods receipts. Backlog: supplier payments and balances, returns to suppliers, freight and landed cost, purchase orders on the platform WhatsApp number, and expected dates shown to shops.
- **Amended (product owner, final review, 2026-10-01):** (a) pages carry search words distributors use ("GST rates", "dues", "bills", "stock count"…), translatable, ranked after names; each settings group is a page too. (b) The products list puts an exact code or barcode first. (c) Reorder points and quantities: whole numbers rounded up for units that can't be split, 2 decimals rounded up otherwise, then up to the supplier's pack; demand told per day from 1 a day, else per week, else per month (`demand_rate`, from the server). (d) Document PDFs attached to emails: ADR-054. (e) A dead product (in stock, not sold in the classification period) below its reorder level is not suggested unless shops wait for it: it is listed apart with a hint to lower the level. Each suggestion leads with the action and its urgency; days of stock are whole days rounded down; "No shop ordered this in the last N days" when the product sold before, "Little sales history" only when it never sold.

## ADR-054 — Documents' PDFs attached to emails
- **Status:** Accepted — 2026-10-01 (product owner, Phase 9a final review).
- **Context:** Emails about documents carried only the secure link (ADR-048 item 8). Shops and suppliers often keep documents straight from their inbox, and the 9a plan said a purchase order is emailed "with the PDF".
- **Decision:**
  1. The shop's emails about an invoice, credit note, receipt, refund voucher or Order Confirmation, and the supplier's purchase order emails (sent and cancelled), attach the document's current PDF as `<number>.pdf` (`/` → `-`) and keep the secure link. Staff emails, WhatsApp and SMS are unchanged. The rule follows the link: a message that carries a document link by email carries the PDF.
  2. The PDF is printed after the business transaction commits, so the email can be due first: it then waits 5 seconds at a time, at most 3 minutes from when it was first due (not counted as a delivery try). A PDF that failed, still isn't ready, can't be read from storage or is over 5 MB is not attached: the email goes with the link alone, never held back or failed for it.
  3. What happened is kept on the message and its delivery attempt (`attachment`: the file, or `NOT_READY`, `PDF_FAILED`, `UNREADABLE`, `TOO_LARGE`).
  4. SES: a message with an attachment is sent as raw MIME (`Content.Raw`), to be verified against the SES v2 reference before production (pre-production item 34).
- **Consequences:** Emails are bigger (document PDFs are typically tens of kilobytes) and can go out up to 3 minutes later when printing is slow. The size limit and waits are constants in `apps/notifications/delivery.py`; a setting can come later if a distributor needs it.

## ADR-055 — Private repository: CI within 3,000 minutes, secrets scanning, staging moved to Phase 10
- **Status:** Accepted — 2026-10-02 (product owner).
- **Context:** The repository was public for a while and is now private for good, on GitHub Pro: 3,000 Actions minutes a month, each job counted separately and rounded up to the minute, with a spending limit. CI used about 47 job-minutes a run (median of 16 green runs on 1 October: backend 11, frontend 3, Playwright 2, full stack 28, images 3), and a commit on a branch with an open pull request ran twice (push and pull request): about 94 job-minutes a commit, 1,538 job-minutes on 1–2 October alone (free while public). Private runners have 2 cores and 8 GB. The owner also wants every feature built before anything goes to staging or production.
- **Decision:**
  1. **Quick checks on every push, once per commit:** backend (lint, types, migrations, the OpenAPI schema, tests on both cores with pytest-xdist, then the timing targets on their own) and frontend (the secrets scan, lint, types, formatting, unit tests, the generated client). Two jobs: one each, not many small ones that each pay their setup and rounding.
  2. **Full suites only when a pull request is marked ready for review, on `main`, and by hand** (`workflow_dispatch`): Playwright on the production build, the full-stack acceptance suites and the responsive check (one job, one stack), the production images and the health probe. The ready-for-review run tests the pull request's merge result; its head's quick checks already ran on push. Developers run the full-stack suites locally before pushing.
  3. **Batched pushes:** push at checkpoints and at the end of a piece of work, not after each commit.
  4. **Cheaper full runs:** the stack's images come from the Docker layer cache (GitHub Actions cache), the web app runs its production build (the dev server compiles every page on its first visit), Playwright's browser is cached; Python and npm too. Every job has a timeout (a full-stack job once hung for hours). Artifacts are kept 7 days.
  5. **Secrets:** gitleaks scans every commit on every branch in CI (seconds) and the staged changes before each commit (`pre-commit`, installed by `make setup`); `.gitleaks.toml` allows only exact public dev and test values. The history scan on 2026-10-02 found nothing real.
  6. **Staging and production move to Phase 10** (task 10.6, with the 9a+ design and cost notes kept in PLAN §10.6); nothing is created in AWS until then. Demos use LAN mode or a temporary tunnel.
  7. **No self-hosted runner for now:** the budget fits without one; a Mac runner would share ports and CPU with the dev stack, run only while the Mac is awake, and execute the repository's code on a personal machine. Revisit if usage passes about 80% of the minutes.
- **Consequences:** A push shows the quick checks in about 8 minutes; the full suites take about 25 minutes when they run. Expected use under typical development (15 pushes and 2 pull requests a week) is about half the monthly minutes. A UI or flow change can break the full-stack suites without CI noticing until the pull request is marked ready, so they are run locally first.
- **Amended (product owner, 2026-10-02, the same day): Actions minutes are no longer limited.** Items 1–3 and 7 give way to: every push runs every check, still once per commit (no pull-request trigger), in parallel jobs: backend and frontend quick checks, Playwright on the production build, the production images, and the full-stack suites as six jobs with a stack each (acceptance in three groups of specs, the responsive check at each width). Pushes need no batching. Items 4–6 stand, except the web image's layers: exporting them to the Actions cache stalled for 17 minutes, so it is built fresh (about 2.5 minutes); the backend image keeps its layer cache.

## ADR-056 — Phase 9b: shop activity and win-back, the daily summary, free-goods schemes
- **Status:** Accepted — 2026-10-02 (lead engineer). The owner asked for all of Phase 9 to be built without stopping for approvals; the choices marked **[assumed]** would normally have been asked and are for the owner to review.
- **Context:** Spec 5.15 (re-engagement insights), the PLAN's 9b (a daily summary for owners, free-goods schemes), the free-goods warning that hides zero-priced products until schemes exist (ADR-034, ADR-036), and the notification framework (ADR-048) with its daily jobs.
- **Decision:**
  1. **Shop activity (core, no flag).** Worked out nightly per distributor (after the stock stats) and on demand (rate limited): each shop's first and last order, orders and their value in the last 90 days and the 90 before (shop cancellations and rejected orders left out, as for demand in ADR-053), the shop's usual gap between orders (median of the gaps between its last 10 orders; needs 3), days since its last order.
  2. **Segments [assumed thresholds, all settings in the Shop settings group]:** *new* (first order within ⚙ `insights.new_days`, 30); *dormant* (no order for ⚙ `insights.dormant_days`, 45); *slowing* (days since the last order above ⚙ `insights.slowing_percent` 150% of the usual gap, at least 7 days; or orders in the last 90 days at most half the 90 before, from at least 3); *never ordered* (added more than 14 days ago); otherwise *active*. Dormant wins over slowing.
  3. **Win back:** slowing, dormant and never-ordered shops not contacted in the last ⚙ `insights.contact_snooze_days` (14). A "Shop activity" screen (segment, salesperson and search filters; cards on phones) with Call, WhatsApp (from the staff member's own phone, a prefilled message — no API), Place an order, and Log a contact (how: call, WhatsApp, visit, other; outcome: reached, no answer, will order, not interested; a note). The contacts are kept per shop (append-only) and shown on the shop's page with its activity. A dashboard tile "Shops to win back". A "Shop activity" report (Excel).
  4. **Who sees what [assumed]:** anyone with `retailers.view`, within the sales-visibility rule (sales staff limited to their own shops see only those); order values only with `reports.sales` or `reports.sales_own`; logging a contact with `retailers.view`. No automatic messages to shops (marketing messages need the shop's opt-in): backlog.
  5. **Daily summary (core).** A new staff-only notification `summary.daily` ("Daily summary"), by default to owners in the app and by email; distributors add WhatsApp or other recipients on "Who gets which message" (the WhatsApp template stays a mock until Meta approves it). ⚙ `notifications.daily_summary_enabled` (on), ⚙ `notifications.daily_summary_time` (08:00 IST), ⚙ `notifications.daily_summary_skip_sunday` (off) [assumed defaults].
  6. **What it says, per recipient and only with their permissions [assumed contents]:** yesterday — orders received (count, value), billed (invoices less credit notes), collected (payments, by mode), new shops; now — orders waiting, on hold, backorders to confirm, to pack, overdue shops and amount, low and out of stock, products to reorder and late purchase orders (modules on), failed IRNs and e-way bills (modules on), shops to win back. A quiet day still sends ("No orders yesterday"). One per person per day, whatever retries or setting changes happen.
  7. **Free-goods schemes (flag `free_goods`, off by default).** A scheme: buy N of a product, get M of a product (the same or another) free; "for every N" (repeats) or once per order line, with an optional cap per order line; for all shops, a price list's shops or one shop; valid from–to; active or not. Created and changed by `pricing.manage`, audited. One scheme per ordered product applies: the one giving the most free units (ties: shop over price list over everyone, then the newest).
  8. **Applied by the server** in the quote, so the cart, checkout, staff orders and changes before acceptance all agree: a separate order line for the free product at ₹0 ("Free under <scheme>"), linked to the line that earned it and to the scheme (name and rule kept on the line). Discounts on the bought line apply as usual; the free line has none. The shop sees "Buy 10 get 1 free" on the product and "Add 2 more to get 1 free" in the cart.
  9. **Stock [assumed]:** a free line reserves stock and backorders like any line; with backorders off and stock short, the free quantity is cut to what is there and the shop is told. When the bought line loses quantity (short supply, cancellation, a change before acceptance), the free line keeps only what the remaining quantity earns, the rest is cancelled — from what still waits or is held; free units already in a shipment stay in it (the warehouse can pack fewer). A change that adds to a line before acceptance is a new line and earns on its own quantity; a free line can be lowered but not raised on its own.
  10. **Invoices and returns [assumed; tax to the CA]:** the free line is invoiced at ₹0 — taxable value 0, no GST — with its HSN and quantity, marked "Free (scheme)". A return credit note may take free units back at ₹0 (stock in), as staff decide; nothing is charged. Free goods shipped on their own get a ₹0 invoice, and free goods alone returned or not supplied a ₹0 credit note, neither touching the ledger. Questions 41–46 in `docs/CA_REVIEW.md` §15a; e-invoices send the free line as its own ₹0 item until the NIC schema's free-quantity field is verified (pre-production item 35).
  11. **Reports:** sales by product show the free quantity; the own-brand vs traded margin counts the cost of free goods.
  12. **The free-goods warning** (ADR-036) stays for ₹0 prices and rules, which still hide the product; with the flag on it suggests a scheme instead.
- **Consequences:** Distributors see who stopped ordering and act on it the same morning; owners get one message instead of opening the dashboard; schemes work end to end with stock and invoices. Backlog: automatic win-back offers, schemes on a whole category or brand ("buy any 10"), slabs of free goods, a weekly summary.

## ADR-057 — Phase 9c: the shop confirms delivery, delivery codes, return requests, the cheque bounce charge
- **Status:** Accepted — 2026-10-02 (lead engineer). Built without stopping for approvals at the owner's request; choices marked **[assumed]** would normally have been asked and are for the owner to review.
- **Context:** ADR-044 item 5 left delivery to staff and put shop confirmation and a proof-of-delivery code on the backlog; ADR-046 item 5 did the same for shop-initiated returns; ADR-048 (checkpoint decision 4) for an optional cheque bounce charge. Shops are non-technical and use phones; the money rules (credit notes only through `invoices.manage`, the append-only ledger) stay as they are.
- **Decision:**
  1. **The shop confirms delivery (core).** On its order page the shop marks a dispatched shipment "Received" (one tap, confirmed). The shipment becomes delivered exactly as when staff mark it (delivered quantities, order status, the shop's timeline and the `order.delivered` message), and the timeline says the shop confirmed it. ⚙ `orders.shop_confirms_delivery` (on) [assumed default]. Staff with `orders.fulfil` can still mark it delivered. A shop that received less or damaged goods uses "Return or report a problem" (item 3), not a partial confirmation [assumed].
  2. **Delivery code (proof of delivery).** ⚙ `orders.delivery_code` (off) [assumed default]. When on, each shipment gets a 4-digit code at dispatch, shown to the shop on the shipment and sent with the dispatch message in the app and by email (WhatsApp once a template carrying it is approved: template parameters can't be empty, so it needs its own template; pre-production item 36). The delivery person (staff with `orders.fulfil`) enters it to mark the shipment delivered; a wrong code is refused, five wrong codes in 15 minutes lock that shipment's code for 15 minutes. Without the code, staff with `orders.fulfil` may still mark it delivered with a reason ("shop closed", "shop didn't have the code" …), audited; the timeline shows "without the delivery code". The shop confirming in its app (item 1) needs no code. The code is stored with the shipment, readable only by the shop's own logins (never in staff screens or exports), and stops working once the shipment is delivered or cancelled.
  3. **Shop return requests (core).** ⚙ `returns.shop_requests` (on), ⚙ `returns.request_days` (30 days from the invoice) [assumed]. From an invoice in the app the shop asks to return quantities of its lines (never more than invoiced less credited and less other open requests), with a reason (the credit note reasons: damaged, expired, wrong item, excess supply, other with a note) and an optional note. The request is REQUESTED → APPROVED, REJECTED (with a reason for the shop) or CANCELLED (by the shop before staff decide). Staff with `invoices.manage` approve it: per line they may lower the quantity and choose what happened to the goods (return to stock, received damaged, not physically returned); approval issues the return credit note through the existing service (stock, ledger, e-invoice, messages all as today) and links it to the request. New messages: `return.requested` (staff: the invoice managers), `return.approved` and `return.rejected` (the shop). A dashboard tile "Return requests", a list under Invoices → Returns with a filter, and the requests on the invoice's page. Free goods (ADR-056) can be asked back at ₹0 like any line. Photos: backlog.
  4. **Cheque bounce charge.** ⚙ `payments.cheque_bounce_charge` (₹0 = off) [assumed default]. When a cheque payment bounces and the charge is above zero, the shop's ledger gets a debit adjustment "Cheque bounce charge" for that amount, linked to the payment, due on the bounce date, counted in ageing and reminders like any debit; no GST (not a tax invoice) [assumed; CA question 47]. It shows on the shop's statement and on the receipt printed again as "Cheque bounced", and the bounced-cheque message names it in the app and by email (WhatsApp: pre-production item 36). No separate numbered document [assumed]. A bounce can't be undone in v1; staff remove a charge with a manual credit adjustment (audited) [assumed]. The charge is audited.
- **Consequences:** Shops close the loop themselves (received, returns), distributors get proof of delivery when they want it, and bounced cheques can carry the cost the bank charges. Nothing changes for tenants who leave the defaults, except that shops can confirm delivery and ask for returns. Backlog: photos on return requests, partial "received less" reports, reversing a bounce automatically, a GST invoice for bounce charges if the CA says so.
