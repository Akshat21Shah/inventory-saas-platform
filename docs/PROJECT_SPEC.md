# Project Specification — Multi-Tenant B2B Inventory & Ordering Platform

Version 1.0. This is the source of truth for what to build. Working rules are in `CLAUDE.md`.

---

## 1. Product overview

A SaaS platform owned by our company. Distributors/dealers subscribe to run their inventory and receive orders from their retailers. Each distributor gets an isolated, brandable workspace. Retailers are non-technical shop owners who order from their distributor through a simple mobile-first app.

### Glossary

| Term | Meaning |
|---|---|
| Platform / Super Admin | Our company. Owns and operates the platform. |
| Tenant / Distributor | A dealer or distributor company using the platform. Owns products, stock, retailers, orders. |
| Retailer / Client | End B2B buyer. Belongs to exactly one distributor. Places orders. |
| Staff | Users working for a distributor (admin, manager, sales, warehouse, accounts). |
| Backorder | Ordered quantity that cannot be fulfilled from current available stock. |
| Available stock | on_hand − reserved. |

### Scale targets (design for these from day one)
- 300+ distributors, up to ~500 retailers each (~150,000 retailers total)
- Up to 20,000 products per distributor
- Millions of order lines and ledger entries over time
- Peak: hundreds of concurrent users per distributor

---

## 2. Roles and permissions

### Platform level
- **Super Admin**: full access to everything, all tenants, platform settings, plans, feature flags, impersonation (audited).
- **Platform Support** (later): read-only cross-tenant access + impersonation with approval.

### Distributor level
| Permission area | Owner/Admin | Manager | Sales | Warehouse | Accounts |
|---|---|---|---|---|---|
| Branding & settings | ✔ | – | – | – | – |
| Staff management | ✔ | – | – | – | – |
| Products & categories | ✔ | ✔ | view | view | view |
| Pricing & discounts | ✔ | ✔ | view | – | view |
| Retailers (create/edit) | ✔ | ✔ | ✔ | – | view |
| Credit limits | ✔ | ✔ | – | – | ✔ |
| Stock inward/adjust | ✔ | ✔ | – | ✔ | – |
| Orders accept/reject/modify | ✔ | ✔ | ✔ | – | – |
| Packing/dispatch | ✔ | ✔ | – | ✔ | – |
| Invoices, e-invoice, e-way bill | ✔ | ✔ | view | – | ✔ |
| Payments & ledger | ✔ | ✔ | view | – | ✔ |
| Reports | ✔ | ✔ | own retailers | stock only | financial |

Implement permissions as named codes (e.g. `orders.accept`) grouped into roles, so custom roles can be added later without code changes.

### Retailer level
- One login per retailer initially (model supports multiple users per retailer later).
- Can: browse catalog, see own prices, place orders, view order status, invoices, ledger/outstanding, make payments (if enabled), manage own profile (limited fields).

---

## 3. Technology stack

See `CLAUDE.md` section 2. Summary: Django + DRF + Celery + Channels + PostgreSQL + Redis; Next.js + TypeScript + Tailwind + shadcn/ui; generated TypeScript API client; React Native (Expo) later; AWS Mumbai region with managed services; Sentry.

---

## 4. Architecture

### 4.1 Repository layout (monorepo)
```
/backend      Django project
/web          Next.js app (platform admin, distributor panel, retailer app as route groups)
/mobile       React Native (Expo) — later phase
/infra        docker-compose, Dockerfiles, deployment config
/docs         PROJECT_SPEC.md, PROGRESS.md, DECISIONS.md
```

### 4.2 Multi-tenancy
- Shared database, shared schema. Tenant-owned tables carry `tenant_id` (indexed, first column in composite indexes).
- `TenantScopedModel` base + tenant-aware manager; tenant stored in a request-scoped context variable.
- PostgreSQL RLS policies as a second line of defence.
- Tenant resolution: from the authenticated user. Subdomain (`{slug}.platform-domain`) is used for branding and the pre-login screen. Platform admin lives at `admin.platform-domain`.

### 4.3 Backend modules (Django apps)
`common`, `platform` (tenants, plans, feature flags, platform settings), `accounts` (users, auth, roles), `catalog`, `pricing`, `retailers`, `inventory`, `orders`, `billing` (invoices, GST, credit notes), `ledger`, `payments`, `compliance` (e-invoice, e-way bill), `notifications`, `reports`, `audit`, `ai` (later).

### 4.4 Cross-cutting
- Domain events (e.g. `OrderPlaced`, `OrderAccepted`, `StockLow`, `InvoiceIssued`, `PaymentReceived`) emitted by services after commit; notifications and real-time updates subscribe to them.
- Real-time: Django Channels group per tenant (`tenant_{id}`) and per retailer; pushes new orders, order status changes, stock alerts.
- External integrations via adapters with `mock` implementations: SMS/OTP, email, WhatsApp, GSP (e-invoice/e-way bill), payment gateway, file storage.
- Feature flags per tenant, managed by Super Admin (some toggleable by distributor admin).

---

## 5. Functional modules

### 5.1 Platform (Super Admin)
- Create/edit/suspend/reactivate tenants. Onboarding wizard: company details, GSTIN, state, address, owner user, subdomain, plan.
- Plans & subscriptions: define plans with limits (retailers, staff users, products, features). **Enforcement is OFF by default** (`PLAN_ENFORCEMENT_ENABLED=false`); all tenants start on a free "Beta" plan. UI sections exist and can be skipped.
- Feature flags per tenant.
- Platform dashboard: tenants count/active, orders and GMV per day, top tenants, failing notifications/integrations, error rates.
- Impersonate a tenant user for support: requires reason, shows a persistent banner, fully audited.
- Global settings: default notification templates, platform-level provider configuration.
- Django admin enabled for super admins only, as an internal ops tool.

### 5.2 Accounts & authentication
- Retailers: login with mobile number + OTP (SMS; WhatsApp OTP as optional channel). Dev/test uses a mock OTP provider.
- Staff & super admin: email + password, optional TOTP 2FA (mandatory for super admin), password reset via email.
- Tokens: short-lived access JWT + refresh token (httpOnly secure cookie for web; secure storage on mobile). Logout revokes refresh token.
- Rate limit OTP requests and login attempts. Lockout with cooldown.
- Staff invitation by email; distributor admin assigns role.

### 5.3 Tenant settings & branding (distributor admin only)
- Branding: display name, logo, primary colour (derive full palette), favicon/app icon, subdomain.
- Business: legal name, GSTIN, PAN, state (state code), addresses, bank details (printed on invoice), invoice terms & footer, authorised signatory image.
- Commercial settings: prices GST-inclusive or exclusive (default exclusive), credit-limit behaviour (`BLOCK` or `REQUIRE_APPROVAL`), show exact stock quantity to retailers (yes/no), allow backorders (default yes), minimum order value (optional), order acceptance mode (manual default; auto-accept optional).
- Invoice series configuration (prefix per financial year).

### 5.4 Catalog
- Categories (nested, max 3 levels), brands, units (pcs, box, kg, litre…, with optional pack conversion e.g. 1 box = 12 pcs).
- Product: name, code (unique per tenant), barcode(s), description, images (multiple, resized), category, brand, unit, HSN code, GST rate (0/5/12/18/28 and configurable), cess (optional, later), MRP, base selling price, min order qty, order multiple, active/inactive, tags.
- Variants: out of scope for v1 (model products flatly; revisit later).
- Bulk import/export via Excel/CSV with validation report (row-level errors), and a downloadable template.
- Search: PostgreSQL full-text + trigram similarity on name, code, barcode, brand, tags. Target < 200 ms.

### 5.5 Retailers
- Profile: shop name, owner name, mobile (login), email, GSTIN (optional but validated if present; unregistered retailers supported), state (required for tax), billing & shipping addresses, assigned price list, credit limit, payment terms (days), status (active/blocked), assigned salesperson, notes.
- Create one-by-one or bulk import. On creation, retailer receives a welcome message with login link.
- A retailer belongs to exactly one tenant (unique constraint on mobile per tenant; the same mobile cannot exist under two tenants in v1).

### 5.6 Pricing & discounts
- Price lists (e.g. "Standard", "Gold retailers") with per-product prices; each retailer assigned one price list (default: base price).
- Retailer-specific product price overrides.
- Discount rules: percentage or flat; scope = product, category, brand, or all; audience = all retailers, price list, or specific retailer; optional quantity slabs; optional validity dates.
- **Resolution order** (implemented in one service, `pricing.services.resolve_price`):
  1. Unit price = retailer override → retailer's price list → product base price.
  2. Discount = the single best applicable active rule (no stacking in v1; stacking flag reserved for later).
  3. Return a structured result: base, unit price, discount applied (rule id + amount), net unit price, tax rate. Store this snapshot on the order line.
- Prices shown to retailers always come from this service.

### 5.7 Inventory
- Warehouses: one default warehouse per tenant; multi-warehouse behind a feature flag (later phase).
- StockLevel per (product, warehouse): `quantity_on_hand`, `quantity_reserved`; available = on_hand − reserved. DB constraints ≥ 0.
- StockMovement (append-only): type (`INWARD`, `SALE`, `RETURN`, `ADJUSTMENT_IN`, `ADJUSTMENT_OUT`, `DAMAGE`, `TRANSFER_IN`, `TRANSFER_OUT`, `RESERVE`, `RELEASE`), quantity, reference (order/invoice/inward id), reason, user, timestamp, resulting balances.
- Stock inward entry (goods received): supplier name/ref, bill number, lines (product, qty, cost price). On save: increase on_hand, then trigger backorder allocation.
- Stock adjustments with mandatory reason (audited).
- Reorder level (min stock) per product. Alerts: `LOW_STOCK` when available ≤ reorder level, `OUT_OF_STOCK` when available = 0, and `BACKORDER_DEMAND` when retailers backorder a product. Alerts de-duplicated (one open alert per product per type until resolved).
- Availability label shown to retailers: `In stock`, `Low stock` (optional), `Available on backorder`. Exact quantity only if tenant setting allows.
- Later (feature-flagged): batches & expiry, stock transfers, purchase orders & suppliers, stock valuation.

### 5.8 Cart & orders
**Cart** (server-side, per retailer): add/update/remove lines; server returns resolved prices, tax estimate, availability and backorder split per line, totals, credit status.

**Placing an order** (single transactional service, idempotent):
1. Re-resolve prices and validate min order qty / multiples / min order value.
2. Lock stock rows; for each line reserve `min(requested, available)`; the remainder becomes backordered quantity (if backorders allowed, otherwise reject the line with a clear message).
3. Credit check: outstanding balance + order value vs credit limit. If exceeded → `BLOCK` (reject with code `CREDIT_LIMIT_EXCEEDED`) or `REQUIRE_APPROVAL` (order status `ON_HOLD`).
4. Create order with number (per tenant sequence, e.g. `ORD-2026-000123`), lines with price snapshot, reserved qty and backordered qty.
5. On commit: emit `OrderPlaced` → real-time push + notification to distributor; confirmation to retailer.

**Order statuses**
```
PLACED ──accept──► ACCEPTED ──► PACKED ──► DISPATCHED ──► DELIVERED
   │                  │
   ├─reject─► REJECTED (reservations released)
   ├─cancel─► CANCELLED (by retailer before acceptance, or by distributor; reservations released)
ON_HOLD (credit approval) ──approve──► PLACED flow / ──reject──► REJECTED
```
- Distributor can modify quantities/remove lines before accepting; retailer is notified of changes.
- Auto-accept is an optional tenant setting.
- Order lines track: ordered, reserved, backordered, invoiced, dispatched quantities.
- Distributor views: separate tabs for New, On hold, Backorders, In progress, Completed; filters by retailer, date, salesperson, status.
- Retailer views: order list, order detail with status timeline, clear indication of backordered items and expected handling.
- Reorder: "Repeat this order" copies lines into the cart with current prices.

### 5.9 Backorders
- Backordered quantities appear in a dedicated distributor queue, grouped by product, showing total demand and waiting retailers (oldest first).
- On stock inward, the allocation service proposes allocation FIFO by order time (tenant setting: auto-allocate or suggest-and-confirm).
- Allocation moves quantity from backordered to reserved and creates a fulfilment that is invoiced separately.
- Retailer is notified when backordered items are allocated. Retailer or distributor can cancel remaining backorder quantity.

### 5.10 Billing & GST
- Invoice generated when an order (or backorder fulfilment) is accepted/allocated. One order can have multiple invoices.
- Invoice numbering: per tenant, per financial year (April–March), configurable prefix, sequential and gapless, max 16 characters, unique within the FY. Generate numbers inside a locked sequence row.
- Tax: compare tenant state code with retailer's place of supply state. Same state → CGST + SGST (rate split equally); different → IGST. Tax computed per line on taxable value (after discount). Invoice total rounded to nearest rupee with a separate round-off line. All logic in `billing/tax.py` with exhaustive tests.
- Invoice content: tenant legal details + GSTIN, retailer details + GSTIN (if any), invoice no/date, place of supply, lines with HSN, qty, unit, rate, discount, taxable value, tax breakup, totals in figures and words, bank details, terms, signatory, and e-invoice IRN + QR code when applicable.
- PDF generated asynchronously (HTML template → PDF), stored in S3, accessible via signed URL.
- Credit notes for returns/cancellations after invoicing (append to ledger as credits).
- Invoices are immutable once issued; corrections via credit note.

### 5.11 E-invoice & e-way bill (feature-flagged per tenant)
- Integrate through a GST Suvidha Provider (GSP) API via an adapter (`compliance/adapters/`), with a `mock` adapter for dev/test. The specific GSP is chosen later; do not hard-code one.
- E-invoice: build the IRN payload from the invoice, submit asynchronously, store IRN, ack no/date, signed QR; retry on failure; show status (`PENDING`, `GENERATED`, `FAILED` with reason) to the distributor; support cancellation within the permitted window.
- E-way bill: generate for eligible invoices (value threshold and transport details: vehicle no, transporter, distance), store EWB number and validity; allow Part-B update.
- Each tenant uses its own GST credentials (encrypted at rest).
- **Verify against current official rules before implementing**: e-invoice applicability thresholds, e-way bill value threshold and state variations, IRN reporting time limits, cancellation windows.

### 5.12 Ledger & payments
- Ledger per retailer (append-only): debit on invoice; credit on payment, credit note, or opening balance adjustment. Maintained running balance on a `RetailerAccount` row updated in the same transaction.
- Outstanding, overdue (by payment terms), ageing buckets (0–30, 31–60, 61–90, 90+).
- **Cash / offline payments**: recorded by staff (amount, mode: cash/cheque/bank transfer/UPI-offline, reference, date, collected by), allocated to invoices (FIFO default or manual).
- **Online payments** (feature-flagged, OFF by default): tenant connects its own gateway account (Razorpay first; adapter interface allows Cashfree etc.). Money settles to the distributor. Retailer can pay an invoice, the outstanding amount, or a custom amount via UPI, cards, net banking. Payment confirmed only via verified webhook; reconciliation job for missed webhooks. Sandbox keys in non-production.
- Receipts generated for every payment.

### 5.13 Notifications
- Channels: in-app (notification centre + real-time), email, WhatsApp (Business API), push (mobile, later), SMS (OTP only by default).
- Event → recipients → channels matrix configurable per tenant (with sensible defaults).
- Key events: order placed/accepted/rejected/modified/dispatched/delivered, backorder allocated, invoice issued (with PDF link), payment received, payment reminder (scheduled for overdue), low/out-of-stock, backorder demand, e-invoice failure, credit hold.
- Templates per tenant with platform defaults; WhatsApp templates must match pre-approved templates (store template name + variables).
- Delivery log with status, provider response, retries; failures visible to distributor admin and super admin.
- Retailer notification preferences (within allowed channels).

### 5.14 Dashboards & reports
- **Distributor dashboard** ("what needs action today"): new orders, on-hold orders, backorders ready to allocate, low/out-of-stock count, overdue receivables, today's sales, pending e-invoices.
- Reports (filterable, exportable to Excel/PDF): sales by period/product/category/retailer/salesperson, stock summary & valuation, stock movement history, low stock, fast/slow/dead stock, backorder report, receivables ageing, collections, GST summary (for filing support: B2B invoice-wise, HSN summary), order fulfilment rate.
- **Retailer home**: search, categories, "Repeat last order", recent orders, outstanding balance, announcements from distributor.
- **Super admin dashboard**: see 5.1.

### 5.15 Smart inventory & AI (later phases, feature-flagged)
- Reorder suggestions from sales velocity (moving average), lead time and safety stock.
- ABC analysis; fast/slow/dead stock classification.
- Demand forecasting (seasonality-aware) — may be a separate Python service if models grow heavy.
- Natural-language / semantic product search for retailers (pgvector embeddings), tolerant of spelling and Hindi/English mix.
- Distributor assistant: ask questions of their own data ("which retailers haven't ordered in 30 days?") using an LLM with tool calls over safe, tenant-scoped read-only query functions (never raw SQL from the model).
- Retailer re-engagement insights (dormant retailers, declining order frequency).
- Supplier bill photo → stock inward draft (OCR/LLM extraction, always human-confirmed).
- All AI calls go through `apps/ai` with provider abstraction, per-tenant usage tracking and limits, and no cross-tenant data in prompts.

### 5.16 Audit log
- Who, what (action code), target object, before/after diff for key fields, IP, user agent, timestamp, impersonation context. Viewable by tenant admin (own tenant) and super admin (all).

---

## 6. Data model outline (starting point, refine in Phase 0 plan)

Platform: `Tenant`, `TenantSettings`, `TenantBranding`, `Plan`, `Subscription`, `FeatureFlag`, `TenantFeature`
Accounts: `User`, `Role`, `Permission`, `Membership` (user↔tenant↔role), `OTPRequest`, `Invitation`
Catalog: `Category`, `Brand`, `Unit`, `Product`, `ProductImage`, `ProductBarcode`
Pricing: `PriceList`, `PriceListItem`, `RetailerPrice`, `DiscountRule`, `DiscountSlab`
Retailers: `Retailer`, `RetailerAddress`, `RetailerUser`
Inventory: `Warehouse`, `StockLevel`, `StockMovement`, `StockInward`, `StockInwardLine`, `StockAlert`
Orders: `Cart`, `CartLine`, `Order`, `OrderLine`, `OrderStatusHistory`, `BackorderAllocation`, `Fulfilment`
Billing: `InvoiceSeries`, `Invoice`, `InvoiceLine`, `CreditNote`, `CreditNoteLine`
Compliance: `EInvoiceRecord`, `EWayBill`
Ledger/Payments: `RetailerAccount`, `LedgerEntry`, `Payment`, `PaymentAllocation`, `GatewayConfig`, `WebhookEvent`
Notifications: `NotificationTemplate`, `NotificationRule`, `Notification`, `DeliveryAttempt`, `DeviceToken`
Audit: `AuditLog`
AI (later): `ProductEmbedding`, `AIUsage`, `Forecast`

All tenant-owned tables: `tenant_id`, `created_at`, `updated_at`, `created_by`; soft delete (`is_active`/`deleted_at`) for master data only, never for financial or stock records.

---

## 7. Non-functional requirements

| Area | Target |
|---|---|
| API latency | p95 < 300 ms for normal endpoints; catalog search < 200 ms |
| Page load | Retailer home interactive < 2.5 s on a mid-range Android phone over 4G |
| Availability | 99.9% monthly for core ordering |
| Data safety | Daily automated backups + point-in-time recovery; tested restore procedure |
| Isolation | Zero cross-tenant data access (tested on every endpoint) |
| Security | OWASP Top 10 addressed; 2FA for super admin; encrypted secrets; HTTPS only; CSP headers |
| Observability | Sentry errors, structured logs with request id + tenant id, health endpoints, Celery queue monitoring, alerting on failures |
| Scalability | Stateless API and workers scale horizontally; heavy reports run async; read replica ready |
| Localisation | English at launch; Hindi and Marathi next; INR formatting (₹1,23,456.00); dates DD-MM-YYYY; timezone Asia/Kolkata |

---

## 8. UI/UX principles

- Clean, calm, modern look. Neutral base, one tenant brand colour for accents, generous whitespace, consistent 8px spacing grid, one font family, clear hierarchy.
- Plain language for retailers; no jargon. Icons always paired with text labels on key actions.
- Mobile-first retailer app, installable PWA (manifest, icons, offline fallback page, push-ready). Bottom navigation: Home, Search/Catalog, Cart, Orders, Account.
- Distributor panel: desktop-first but fully usable on tablet/phone; left sidebar navigation; command/search bar; data tables with saved filters.
- Every action gives feedback (toast/inline), destructive actions confirm, forms validate inline with helpful messages.
- Status colours consistent across the app (e.g. placed = blue, on hold = amber, rejected = red, delivered = green) always paired with text.
- Skeleton loaders, empty states with a helpful next action, friendly error states with retry.
- Numbers: money right-aligned in tables, INR formatting, tax breakup visible on demand.

---

## 9. Environments & deployment

- Environments: local (Docker Compose), staging, production. Staging mirrors production with sandbox integrations.
- CI (GitHub Actions): lint, type check, tests, build images, run migrations check; deploy to staging on main; production on tagged release with manual approval.
- Production (AWS ap-south-1 Mumbai): containers for API, Channels/ASGI, Celery workers, Celery beat; managed PostgreSQL (Multi-AZ); managed Redis; S3 + CDN for media and static; secrets in a secrets manager.
- Zero-downtime deploys; backward-compatible migrations (expand → migrate → contract).

---

## 10. Integrations (all behind adapters with mock implementations)

| Integration | Purpose | Notes to verify before production |
|---|---|---|
| SMS provider | OTP | India DLT registration of sender ID and templates |
| Email (e.g. AWS SES) | Transactional email | Domain verification, SPF/DKIM |
| WhatsApp Business (Meta Cloud API or BSP) | Invoices, order updates, reminders | Template approval, per-conversation pricing, opt-in |
| GSP | E-invoice, e-way bill | Provider selection, sandbox access, current GST rules |
| Payment gateway (Razorpay first) | Online retailer payments | Per-tenant merchant accounts, webhook signatures |
| LLM provider | AI features | Data handling, cost limits per tenant |

---

## 11. Out of scope for v1
Product variants, multi-currency, iOS app, marketplace across distributors, retailer belonging to multiple distributors, accounting software sync (Tally etc.), logistics partner APIs. Keep the design open to these.

---

## 12. Phased roadmap

Each phase ends with a working, demoable, tested increment. Do not start a phase until the previous one meets its acceptance criteria.

### Phase 0 — Foundation
Monorepo, Docker Compose, Django project with settings split, Next.js app, Tailwind + shadcn/ui design system (tokens, core components, layout shells for the three areas), i18n setup, OpenAPI + client generation, `common` app (base models, tenant context, RLS helper, error format, pagination), Sentry, logging, CI, Makefile, seed command skeleton.
**Accept when:** `make up` runs everything; health checks pass; CI green; design system page renders core components.

### Phase 1 — Tenancy, auth, platform admin
Tenant model and onboarding, feature flags, plans (non-enforced Beta), staff auth (email/password, 2FA for super admin), retailer OTP auth (mock provider), roles & permissions, invitations, tenant branding & settings, super admin panel (tenants list/detail/create/suspend, feature flags, impersonation with audit), audit log base.
**Accept when:** super admin creates a distributor; distributor admin logs in, sets branding, invites staff; tenant isolation tests pass for all endpoints.

### Phase 2 — Catalog, retailers, pricing
Categories, brands, units, products (images, HSN, GST), bulk import/export, product search, retailers (CRUD, bulk import, welcome message via mock), price lists, retailer overrides, discount rules, `resolve_price` with full tests.
**Accept when:** distributor imports 1,000 products and 100 retailers from Excel; a retailer logs in and sees only their distributor's products with correctly resolved prices.

### Phase 3 — Inventory
Default warehouse, stock levels, movement log, stock inward, adjustments, reorder levels, stock alerts (deduplicated), stock screens and reports (summary, movement history, low stock), availability labels for retailers.
**Accept when:** inward and adjustments update stock with correct movements; alerts fire once; concurrency test passes.

### Phase 4 — Ordering & backorders
Retailer storefront (PWA): home, search, category browse, product detail, cart, checkout, orders, repeat order. Order placement service (idempotent, reservation, backorder split, credit check stub using current outstanding = 0 until Phase 5), distributor order management (tabs, accept/reject/modify, pack/dispatch/deliver), real-time new-order push, status history, backorder queue and allocation on inward.
**Accept when:** end-to-end Playwright test: retailer orders in-stock + out-of-stock items → distributor sees it live → accepts → backorder allocated after inward; no overselling under concurrent orders.

### Phase 5 — Billing, GST, ledger, credit control
Invoice series, tax engine, invoice generation on acceptance/allocation, PDF, credit notes, retailer ledger, offline payment recording and allocation, outstanding/ageing, real credit limit enforcement (BLOCK / REQUIRE_APPROVAL with ON_HOLD flow), retailer invoices & ledger screens.
**Accept when:** tax engine tests cover intra/inter-state, discounts, rounding, multiple rates; ledger balances reconcile with invoices − payments − credit notes in automated tests.

### Phase 6 — Notifications
Notification service, rules matrix, templates, in-app notification centre, email (mock → SES), WhatsApp adapter (mock → provider), delivery log, retries, scheduled payment reminders, retailer preferences.
**Accept when:** every key event produces the correct notifications per channel; failures are logged, retried and visible.

### Phase 7 — Compliance & online payments (feature-flagged)
GSP adapter with e-invoice (IRN, QR on PDF, cancel) and e-way bill; payment gateway adapter (Razorpay) with tenant onboarding of keys, checkout for invoices/outstanding, verified webhooks, reconciliation job, receipts.
**Accept when:** sandbox end-to-end flows succeed; with flags off, the app behaves exactly as before.

### Phase 8 — Dashboards & reports
Distributor action dashboard, full report set with export, super admin platform dashboard, GST summary reports.
**Accept when:** reports on seeded data of 50k orders load within targets (heavy ones async with download link).

### Phase 9 — Smart inventory & AI
Reorder suggestions, ABC and movement classification, semantic search, distributor data assistant, re-engagement insights, (optional) batches/expiry, multi-warehouse, suppliers & purchase orders.
**Accept when:** features are flag-gated, tenant-scoped, usage-tracked, and degrade gracefully if the AI provider is down.

### Phase 10 — Hardening & launch
Hindi/Marathi translations, accessibility pass, performance/load testing, security review (dependency audit, permission review, pen-test checklist), backup-restore drill, runbooks, production deployment, subscription enforcement ready to switch on.

### Phase 11 — Android app
Expo app for retailers (and later distributor staff) using the generated API client: OTP login, catalog, cart, orders, invoices, payments, push notifications (FCM), tenant branding applied at runtime from the server. Single app on Play Store; branded builds per tenant as a future option.
