# Project Specification — Multi-Tenant B2B Inventory & Ordering Platform

Version 1.10. This is the source of truth for what to build. Working rules are in `CLAUDE.md`. Design details are in `docs/PLAN.md`; decisions are in `docs/DECISIONS.md`.

**Changelog**
- **1.10 (2026-10-02)** — Phase 9b (ADR-056): shop activity with segments (new, active, slowing, dormant, never ordered), win-back actions and a contacts log; a daily summary for owners by app, email or WhatsApp; free-goods schemes ("buy N get M free", flag `free_goods`) applied by the server, with ₹0 free lines on orders and invoices. Staging and production infrastructure moved to Phase 10; the repository is private (ADR-055).
- **1.9 (2026-10-01)** — Phase 9 split into 9a–9e with staging after 9a and an after-launch list; Phase 9a plan (ADR-053): global search (core, always on), nightly product stats with ABC and movement classes, suppliers and purchase orders (flag `purchasing`), receiving against purchase orders with an over-receipt tolerance, reorder suggestions that explain themselves (flag `stock_planning`), quantity on order visible to staff; Platform Support role and the Tally / GSTR-1 JSON files in Phase 10.
- **1.8 (2026-09-30)** — Phase 8 plan (ADR-050): one report framework with permissions and own-shop scope built in; "Orders received" and "Billed" on the dashboard; the salesperson recorded on each order and the cost on each invoice line (margins); fast / slow / dead / new stock; the GST summary workbook for a month or a quarter; background exports with a "Report ready" message; the Tally export designed and on the backlog.
- **1.7 (2026-09-29)** — Phase 7 plan (ADR-049): turnover band setting; IRNs for B2B invoices and their credit notes only; IRN cancellation re-issues a corrected invoice (default) or takes the goods back; e-way bill thresholds between states and within the state, distance per shop address; one active online checkout per bill; WhatsApp template approval status.
- **1.6 (2026-09-29)** — Phase 6 plan (ADR-048): WhatsApp opt-in consent, compulsory events, secure document links, quiet hours, payment-reminder cadence and pauses, handover reminders, GST rate-change warning job, per-tenant WhatsApp sender, WhatsApp cost estimate.
- **1.5 (2026-09-28)** — Phase 5 plan (ADR-046): invoice/credit-note/receipt number format, Order Confirmation PDF, return dispositions per line and return reasons, salesman collections with handover tracking, ageing basis setting, automatic use of advances with reallocation.
- **1.1 (2026-09-24)** — Product-owner decisions applied:
  - per-shipment fulfilment model and the COMPLETED status;
  - invoice timing setting (default at dispatch) and the Order Confirmation document;
  - GST rate master (GST 2.0) with effective-dated product rates;
  - fixed tax/credit/numbering rules;
  - retailer mobile unique **per tenant** (was platform-wide) with a generic-domain account chooser;
  - configurability principle and settings registry (§13);
  - payments (advances, cheques);
  - backorder FIFO policy.
- **1.4 (2026-09-27)** — Phase 4 decisions (ADR-044): credit stub before billing, staff carts per shop and staff member, saved delivery addresses, flaky-network checkout, quick ordering from product cards.
- **1.3 (2026-09-26)** — Cost permissions (`costs.view` / `costs.manage`) separate from pricing; one opening-stock adjustment per file; low-stock report counts products without a reorder level (ADR-042).
- **1.2 (2026-09-26)** — Phase 3 plan decisions (ADR-041): cost method setting, receiving without cost ("complete costs" later), valuation at cost price in Phase 3, multi-line adjustments with counted quantities, out-of-stock products in the shop setting, movement types open for manufacturing.

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
| Shipment (Fulfilment) | A packed-and-dispatched part of an order: the initial one, or one per backorder allocation. Each has its own status and invoice. |
| Setting | A configurable business rule with a safe default (see §13). |

### Scale targets (design for these from day one)
- 300+ distributors, up to ~500 retailers each (~150,000 retailers total)
- Up to 20,000 products per distributor
- Millions of order lines and ledger entries over time
- Peak: hundreds of concurrent users per distributor

---

## 2. Roles and permissions

### Platform level
- **Super Admin**: full access to everything, all tenants, platform settings, plans, feature flags, impersonation (audited).
- **Platform Support** (Phase 10): read-only cross-tenant access + impersonation with approval.

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
  - Retailers normally log in on their distributor's subdomain.
  - On the generic platform domain, if the verified number belongs to retailer accounts under more than one distributor, a "choose your distributor" screen is shown after OTP verification.
  - Responses never reveal whether a number is registered.
- Staff & super admin: email + password, optional TOTP 2FA (mandatory for super admin), password reset via email.
  - Distributor staff log in on their tenant subdomain, or on the generic `<domain>/login` (tenant resolved from their memberships, with a chooser if they belong to more than one tenant).
  - Super admin logs in only at `admin.<domain>`.
- Tokens: short-lived access JWT + refresh token (httpOnly secure cookie for web; secure storage on mobile). Logout revokes refresh token.
- Rate limit OTP requests and login attempts. Lockout with cooldown.
- Staff invitation by email; distributor admin assigns role.

### 5.3 Tenant settings & branding (distributor admin only)
- Branding: display name, logo, primary colour (derive full palette), favicon/app icon, subdomain.
- Business: legal name, GSTIN, PAN, state (state code), addresses, bank details (printed on invoice), invoice terms & footer, authorised signatory image.
- Commercial settings are defined by the settings registry (§13) and edited on generated settings pages grouped as Tax, Invoicing, Orders, Stock, and Credit & Payments. Key defaults:
  - prices GST-exclusive;
  - credit breach → require approval;
  - exact stock hidden from retailers;
  - backorders on, with allocation confirmed by the distributor;
  - no minimum order value;
  - manual order acceptance;
  - invoice at dispatch.
- GST registration type: only "regular" in v1 (GSTIN mandatory for every distributor); "composition / bill of supply" is reserved for later.
- Invoice series configuration (prefix per financial year).

### 5.4 Catalog
- Categories (nested, max 3 levels), brands, units (pcs, box, kg, litre…, with optional pack conversion e.g. 1 box = 12 pcs).
- Product: name, code (unique per tenant), barcode(s), description, images (multiple, resized), category, brand, unit, HSN code, GST rate + optional cess (**effective-dated**, see below), MRP, base selling price, min order qty, order multiple, active/inactive, tags.
- GST rates come from a platform-managed rate table (super admin):
  - seeded active 0, 0.25, 3, 5, 18, 40 (GST 2.0, effective 22-Sep-2025);
  - seeded inactive 12, 28, which remain valid on historical invoices and their credit notes.
- Cess types and an optional HSN → rate hint table are also platform-managed.
- A product's rate is a history of (rate, cess, effective-from date). Changes can be scheduled in advance, individually or in bulk by HSN/category.
  - Distributors are warned 7 days before a scheduled change (dashboard card + notification).
  - With GST-inclusive prices, the inclusive price stays the same and the taxable value changes.
- Variants: out of scope for v1 (model products flatly; revisit later).
- **Own brand (white label):** a distributor can mark a brand as its own brand. The product list filters by it, and a tenant setting (default off) shows an "own brand" badge in the shop.
- **Cost price** per product:
  - Visible only to staff with the cost permission (`costs.view` to see, `costs.manage` to change; ADR-042). Sales staff see selling prices but not costs. Never sent to shops. Audited on change.
  - Kept so margins can be reported later (own brand vs traded).
  - Optional column in product import/export, which needs the pricing permission.
- Manufacturing (raw materials, bills of materials, production entries with cost roll-up) is a future phase (PLAN backlog).
- Bulk import/export via Excel/CSV with validation report (row-level errors), and a downloadable template.
- Search: PostgreSQL full-text + trigram similarity on name, code, barcode, brand, tags. Target < 200 ms.

### 5.5 Retailers
- Profile: shop name, owner name, mobile (login), email, GSTIN (optional but validated if present; unregistered retailers supported), state (required for tax), billing & shipping addresses, assigned price list, credit limit, payment terms (days), status (active/blocked), assigned salesperson, notes.
- Create one-by-one or bulk import. On creation, retailer receives a welcome message with login link.
- A retailer account belongs to exactly one tenant. The mobile number is unique **per tenant**. The same person/shop may have separate retailer accounts under different distributors, with fully separate data. A distributor is never told that a number exists under another tenant.

### 5.6 Pricing & discounts
- **Price lists** (e.g. "Standard", "Gold retailers") with per-product prices. Each retailer is assigned one price list; without one, the base price applies.
- **Retailer-specific product prices** (special prices).
- **Discount rules:**
  - Percentage, or flat per unit.
  - Scope: product, category (with its sub-categories), brand, or all products.
  - Audience: all retailers, a price list, or one retailer.
  - Optional quantity slabs and validity dates.
  - Every product can have its own discount, set per product and per shop (or price list). Many products have none.
- **Combining discounts** is a tenant setting, `pricing.discount_combination` (ADR-038):
  - **Best single discount** (default): the one rule giving the largest discount.
  - **Add them together:** each rule's amount is worked out on the original line, and the amounts are added (5% + 10% = 15%).
  - **One after another:** from the most specific rule to the least specific, each applied to what is left (10% then 5% = 14.5%).
  - In every mode, the total discount never exceeds the line amount.
- **Resolution** (one service, `pricing.resolve_price`):
  1. Unit price = retailer special price → retailer's price list → product base price.
  2. Discount = the applicable active rules, combined as the setting says.
  3. A structured result: base, unit price, every rule applied (rule, amount), total discount, net unit price, tax rate. The order line stores this snapshot (Phase 4).
- **What shops see:**
  - Prices always come from this service.
  - The total discount, as an amount and a percentage ("You save ₹12 (12%)"), and "Buy more, pay less" slab hints.
  - Never rule names, how many rules applied, base prices or cost prices.
- **Free-goods schemes** ("buy N get M free", Phase 9b, flag `free_goods`, ADR-056): buy N of a product, get M of the same or another product free, repeating "for every N" or once, with an optional cap; for all shops, a price list or one shop; valid dates. The server adds the free goods as a ₹0 line linked to the line that earned them (the best scheme per product); the shop sees "Buy 10 get 1 free" and "Add 2 more to get 1 free". Free lines reserve and backorder stock like other lines and shrink with the bought line. A rule, special price or price-list price that brings a net price to zero is still saved with a warning and hides the product from those shops (ADR-034, ADR-036).
- **Managing pricing at scale** (hundreds of shops, thousands of products; ADR-037):
  - **Per shop:**
    - A "what this shop pays" table with inline special prices.
    - A discount grid (discount per product, net price previewed by the server).
    - "Add a discount for this shop".
    - "Copy pricing from another shop" (Replace or Add, chosen each time, with a preview; audited).
  - **Bulk and reporting:**
    - Bulk price-list change by percentage for a category or brand (preview first; paisa or whole-rupee rounding).
    - A report of shops with special prices or shop-specific rules, including products that become free.
  - Excel import/export (explicit mode, change preview, error report) for special prices, price-list prices and discount rules.

### 5.7 Inventory
- Warehouses: one default warehouse per tenant; multi-warehouse behind a feature flag (later phase).
- StockLevel per (product, warehouse): `quantity_on_hand`, `quantity_reserved`; available = on_hand − reserved. DB constraints ≥ 0.
- StockMovement (append-only): type (`INWARD`, `SALE`, `RETURN`, `ADJUSTMENT_IN`, `ADJUSTMENT_OUT`, `DAMAGE`, `TRANSFER_IN`, `TRANSFER_OUT`, `RESERVE`, `RELEASE`), quantity, reference (order/invoice/inward id), reason, user, timestamp, resulting balances. Types are data, so manufacturing can add "consume raw material" and "produce finished goods" later without restructuring (ADR-041).
- Stock inward entry (goods received): supplier name/ref, bill number, lines (product, qty in base unit or packs, "Cost per unit (before GST)"). On save: increase on_hand, then trigger backorder allocation.
  - Staff without cost access post quantities only; those lines are "cost pending" until someone who manages costs completes them (audited). A "Goods receipts awaiting cost" list shows them.
- **Cost method** (tenant setting): posted costs update the product's cost price by weighted average (default), to the last purchase cost, or never (manual only). Manual edits are always possible and audited.
- Stock adjustments: several products at once, one reason code and a required note (audited); each line adds, removes, or records a counted quantity. Reserved stock cannot be removed.
- Reorder level (min stock) per product, editable with product or stock-adjust permission (audited). Alerts: `LOW_STOCK` when available ≤ reorder level, `OUT_OF_STOCK` when available = 0, and `BACKORDER_DEMAND` when retailers backorder a product. Alerts de-duplicated (one open alert per product per type until resolved).
- Availability label shown to retailers: `In stock`, `Low stock` (optional), `Available on backorder`, `Out of stock`. Exact quantity only if tenant setting allows. A tenant setting hides out-of-stock products instead (default: shown).
- Reports: low stock (with a count of active products that have no reorder level, linking to them), and stock valuation (quantity × cost price, category and brand totals; products without a cost price marked and excluded from totals), with Excel export.
- Fast entry on phones and tablets: product search, typed or scanner (USB/Bluetooth) barcodes, and the phone camera where the browser supports it.
- Purchasing (flag `purchasing`, Phase 9a, ADR-053): suppliers (with an Excel import), several suppliers per product with one preferred, purchase orders (draft, sent, partly received, received, closed, cancelled) emailed to the supplier as a PDF with a share link, prices before GST with GST estimated for information. Receiving against a purchase order fills in a goods receipt with what is still due and the order's costs; more than ordered is accepted up to a tolerance (setting, 10%), above it only with a manager's confirmation. Staff who see orders or stock see a product's quantity on order and expected date, without supplier or price.
- Later (after launch, feature-flagged): batches & expiry, multi-warehouse and stock transfers.

### 5.8 Cart & orders
**Cart** (server-side, per retailer): add/update/remove lines; server returns resolved prices, tax estimate, availability and backorder split per line, totals, credit status.

**Placing an order** (single transactional service, idempotent; placed by the retailer or, if enabled, by staff on the retailer's behalf, and `placed_by` is recorded):
1. Re-resolve prices and validate min order qty / multiples / min order value (optional setting; basis incl. or excl. GST is a setting; backordered items count).
2. Lock stock rows; for each line reserve `min(requested, available)`; the remainder becomes backordered quantity.
   - If backorders are off, the setting decides: **fail** the order and show which items are short, with a one-tap "reduce to available" (default); or **place the in-stock part** and cancel the rest with a clear message.
3. Credit check (fixed formula): ledger balance + value of open not-yet-invoiced orders + this order, vs the credit limit.
   - Empty limit = unlimited; 0 = no credit.
   - Optionally, invoices overdue beyond N days count as a breach (setting, default off).
   - On breach, the setting decides: require approval (`ON_HOLD`, default) or block (`CREDIT_LIMIT_EXCEEDED`).
   - Orders on hold reserve stock by default (setting).
4. Create order with number (per tenant sequence, e.g. `ORD-2026-000123`), lines with price snapshot, reserved qty and backordered qty, and a **snapshot of the settings in effect**.
5. On commit: emit `OrderPlaced` → real-time push + notification to distributor; confirmation to retailer.

**Order statuses**
```
PLACED ──accept──► ACCEPTED ──► PACKED ──► DISPATCHED ──► DELIVERED
   │                  │
   ├─reject─► REJECTED (reservations released)
   ├─cancel─► CANCELLED (by retailer before acceptance, or by distributor; reservations released)
ON_HOLD (credit approval) ──approve──► PLACED flow / ──reject──► REJECTED
... ──► COMPLETED (all shipments delivered and no open backorder quantity)
```
- Every shipment (the initial one and each backorder allocation) has its own packing, dispatch, invoice and status. After acceptance the order status follows its shipments. **COMPLETED** = all shipments delivered and no open backorder quantity.
- At acceptance, an **Order Confirmation** document (items, prices, tax estimate) is sent through the normal notification channels (setting, default on). It carries the line "This is not a tax invoice."
- With "full edit", an edit that would exceed the retailer's credit limit is refused unless a user with credit permission applies an audited override in the same flow.
- Before accepting, the distributor can reduce/remove lines (default), or also add lines and increase quantities if the "full edit" setting is on (credit re-checked). The retailer is always notified of changes.
- Sales staff see all orders by default; a setting restricts them to their assigned retailers.
- Unaccepted orders never expire; a dashboard alert appears after N hours (setting, default 24).
- Auto-accept is an optional tenant setting.
- Order lines track: ordered, reserved, backordered, invoiced, dispatched quantities.
- Distributor views: separate tabs for New, On hold, Backorders, In progress, Completed; filters by retailer, date, salesperson, status.
- Retailer views: order list, order detail with status timeline, clear indication of backordered items and expected handling.
- Reorder: "Repeat this order" copies lines into the cart with current prices.
- Quick ordering: the quantity stepper and "Add" are on product cards in search results, category lists and "Repeat last order"; the cart in the bottom navigation shows the item count; a product in stock goes from search to a placed order in 3 taps (ADR-044).
- Checkout: the shop picks a saved delivery address (default shipping pre-selected; place of supply follows its state) and can add delivery instructions. A submission on a poor connection is retried with the same key, so it can never create two orders (ADR-044).

### 5.9 Backorders
- Backordered quantities appear in a dedicated distributor queue, grouped by product, showing total demand and waiting retailers (oldest first).
- On stock inward, the allocation service allocates FIFO by order time **in the same transaction as the inward**, so older backorders are served before new orders.
  - Only accepted orders are eligible.
  - Credit is re-checked, and retailers over their limit are skipped and flagged.
  - Tenant setting: confirm each allocation (default) or auto-allocate. Proposals awaiting confirmation hold the stock.
- Allocation moves quantity from backordered to reserved and creates a shipment that is invoiced separately. The billing price is the original order price (default) or the current price (setting).
  - With current pricing, if the price has **increased**, the retailer is notified and may cancel that quantity themselves until the shipment is packed.
  - If the price is unchanged or lower, the retailer only gets a notification.
- Permission `orders.allocate_backorder` is granted by default to Owner/Admin, Manager and Warehouse.
- Retailer is notified when backordered items are allocated. Retailer or distributor can cancel remaining backorder quantity.

### 5.10 Billing & GST
- Invoice timing is a tenant setting (snapshotted per order):
  - **At dispatch (default).** The invoice covers the packed quantity when the warehouse confirms packing and dispatches. A short-packed remainder becomes backorder (if backorders are on) or is cancelled, and the retailer is notified.
  - **At acceptance / allocation.** Short packs are corrected with a credit note.
  - One order can have multiple invoices (one per shipment).
  - The e-way bill is generated from the invoice at dispatch in both modes.
- The tax rate applied is the one **valid on the invoice date** (fixed rule). The distributor sees a warning when it differs from the order-time rate.
- Issued invoices are never edited or cancelled; corrections are always via credit notes. The only exception is e-invoice (IRN) cancellation within the permitted window.
- Invoice numbering: per tenant, per financial year (April–March), configurable prefix, sequential and gapless, max 16 characters, unique within the FY. Generate numbers inside a locked sequence row.
- Tax (fixed rules):
  - Compare the tenant state code with the place of supply.
  - Place of supply = the shipping address state, defaulting to the retailer's registered state.
  - Same state → CGST + SGST (rate split equally); different → IGST.
  - Tax is computed per line on the taxable value (after discount).
- Rounding defaults (pending CA confirmation): each tax component rounded half-up to the paisa, and the invoice total rounded to the nearest rupee with a separate round-off line. Rounding to the rupee on/off and the rounding methods are tenant settings, limited to a vetted list.
- Every invoice reconciles to the paisa. All logic lives in `billing/tax.py`, with exhaustive tests covering every setting value.
- Invoice content: tenant legal details + GSTIN, retailer details + GSTIN (if any), invoice no/date, place of supply, lines with HSN, qty, unit, rate, discount, taxable value, tax breakup, totals in figures and words, bank details, terms, signatory, and e-invoice IRN + QR code when applicable.
- PDF generated asynchronously (HTML template → PDF), stored in S3, accessible via signed URL.
- Credit notes for returns/cancellations after invoicing (append to ledger as credits). For returns, each line says what happened to the goods: returned to stock (default), received damaged (written off), or not physically returned; a return reason is required (ADR-046).
- Invoices are immutable once issued; corrections via credit note.

### 5.11 E-invoice & e-way bill (feature-flagged per tenant)
- Integrate through a GST Suvidha Provider (GSP) API via an adapter (`compliance/adapters/`), with a `mock` adapter for dev/test. The specific GSP is chosen later; do not hard-code one.
- E-invoice: build the IRN payload from the invoice, submit asynchronously, store IRN, ack no/date, signed QR; retry on failure; show status (`PENDING`, `GENERATED`, `FAILED` with reason) to the distributor; support cancellation within the permitted window.
- E-way bill: generate for eligible invoices (value threshold and transport details: vehicle no, transporter, distance), store EWB number and validity; allow Part-B update.
- Each tenant uses its own GST credentials (encrypted at rest).
- **Verify against current official rules before implementing**: e-invoice applicability thresholds, e-way bill value threshold and state variations, IRN reporting time limits, cancellation windows.
- Phase 7 decisions (ADR-049): the distributor declares an annual turnover band (below ₹5 crore / ₹5–10 crore / ₹10 crore and above), which drives suggestions and the reporting-limit warning only. IRNs for B2B invoices and their credit notes, automatic by default; a permanent failure leaves the invoice valid, marked "IRN failed". The shop's bill message waits for the IRN, at most 10 minutes. Cancelling an IRN (within the window) re-issues a corrected invoice with a new number for the same shipment (default) or takes the goods back. E-way bill thresholds between states and within the state (settings); the distance comes from the shop's address and can be changed at dispatch; dispatch never waits.

### 5.12 Ledger & payments
- Ledger per retailer (append-only): debit on invoice; credit on payment, credit note, or opening balance adjustment. Maintained running balance on a `RetailerAccount` row updated in the same transaction.
- Outstanding, overdue (by payment terms), ageing buckets (0–30, 31–60, 61–90, 90+).
- **Cash / offline payments**: recorded by staff (amount, mode: cash/cheque/bank transfer/UPI-offline, reference, date, collected by), allocated to invoices (FIFO default or manual).
- Advances/overpayments are held as credit and applied to future invoices (setting, default on). When off, overpayments are refused; a credit note exceeding the invoice balance still leaves a credit balance for the next invoice.
- Cheques are credited on receipt (default, with an automatic reversing entry if the cheque bounces) or only on clearance (setting).
- **Online payments** (feature-flagged, OFF by default): tenant connects its own gateway account (Razorpay first; adapter interface allows Cashfree etc.). Money settles to the distributor. Retailer can pay an invoice, the outstanding amount, or a custom amount via UPI, cards, net banking. Payment confirmed only via verified webhook; reconciliation job for missed webhooks. Sandbox keys in non-production. One active checkout per shop per bill (or per "pay everything" / custom amount): a second tap reuses it. An amount that differs from the checkout is recorded as paid and flagged for staff (ADR-049).
- Receipts generated for every payment.
- **Salesman collections** (ADR-046): sales staff with `payments.collect` record cash, cheque and UPI collections from their own shops (setting, default on). The shop is credited and gets a receipt at once; the payment stays "With salesman" until Accounts/Manager/Owner confirm "Handed over". A pending-handover report per salesman.
- Receivables ageing by invoice date (default) or days past due (setting). Advances are applied automatically to new invoices, oldest money first; staff can reverse and reallocate an allocation.

### 5.13 Notifications
- Channels: in-app (notification centre + real-time), email, WhatsApp (Business API), push (mobile, later), SMS (OTP only by default).
- Event → recipients → channels matrix configurable per tenant (with sensible defaults).
- Key events: order placed/accepted/rejected/modified/dispatched/delivered, backorder allocated, invoice issued (with PDF link), payment received, payment reminder (scheduled for overdue), low/out-of-stock, backorder demand, e-invoice failure, credit hold.
- Templates per tenant with platform defaults; WhatsApp templates must match pre-approved templates (store template name + variables).
- Delivery log with status, provider response, retries; failures visible to distributor admin and super admin.
- Retailer notification preferences (within allowed channels). Events the distributor marks compulsory (by default invoices, credit notes, bounced cheques, payment reminders) can't be switched off; in-app never can.
- WhatsApp only to shops that opted in (in the app, recorded by staff with confirmation, or imported), with timestamp and source; opting out is always possible. The rules screen shows the opted-in count and an estimated monthly WhatsApp cost per event (platform price per message category).
- Invoices, credit notes, receipts, refund vouchers and the Order Confirmation are sent as secure links (one document, no sign-in, 30 days by default, revocable) that always show the current document.
- Quiet hours (default 21:00–08:00) hold reminders and other non-urgent WhatsApp, SMS and email until morning; messages about what the shop just did go at once; in-app is never held.
- Payment reminders on a configurable cadence (default 2 days before due, then 3, 7, 15, 30 days overdue, then every 15 days), one message per shop listing its overdue bills; staff with credit management can pause them per shop. Handover reminders to salesmen and Accounts after a set number of days. A daily GST rate-change warning 7 days ahead.
- One platform WhatsApp number for now, naming the distributor in every message; a distributor's own number can be connected later.

### 5.14 Dashboards & reports
- **Distributor dashboard** ("what needs action today" first): new orders, on-hold orders, backorders to confirm, failed IRNs and e-way bills, collections pending handover, overdue receivables, low/out-of-stock count; then today's **Orders received** (orders placed, incl. GST) and **Billed** (invoices minus credit notes); then trends (billed per day for 30 days vs the 30 before, top 5 products and shops this month, new vs repeat shops). Each part only with its permission (ADR-050).
- Reports (filterable, exportable to Excel; PDF for the sales summary, ageing, collections and the GST summary; heavy exports in the background with a "Report ready" message): sales by period/product/category/brand/retailer/salesperson, sales by invoice (the sales register: every invoice and credit note), own brand vs traded margin (with `costs.view`), stock summary & valuation, stock movement history, low stock, fast/slow/dead/new stock (by value or quantity, over a set period), backorder demand, receivables ageing, collections and salesperson collections, GST summary for a month or a quarter (laid out like the GSTR-1 template: B2B invoice-wise, B2C large and others, credit notes, HSN summary for B2B and B2C, documents issued), order fulfilment rate. Every report respects the user's permissions: cost columns only with `costs.view`; sales staff see only their own shops when the distributor chose that.
- Accounting export for Tally (sales invoices, credit notes, receipts): designed (ADR-050), built when a real TallyPrime import can be tested.
- **Retailer home**: search, categories, "Repeat last order", recent orders, outstanding balance, announcements from distributor.
- **Super admin dashboard**: see 5.1.

### 5.15 Smart inventory & AI (later phases, feature-flagged)
- Reorder suggestions from daily demand (quantity ordered over a set window), lead time and safety stock, each explained in plain words ("sold 120 in 30 days, 9 days of stock left, supplier takes 7 days"); staff change, dismiss or turn them into purchase orders, and can use the reorder point as the reorder level. No AI needed (flag `stock_planning`, Phase 9a).
- ABC analysis; fast/slow/dead/new stock classification, kept per product by a nightly job (Phase 9a).
- Demand forecasting (seasonality-aware) — may be a separate Python service if models grow heavy.
- Natural-language / semantic product search for retailers (pgvector embeddings), tolerant of spelling and Hindi/English mix.
- Distributor assistant: ask questions of their own data ("which retailers haven't ordered in 30 days?") using an LLM with tool calls over safe, tenant-scoped read-only query functions (never raw SQL from the model).
- Retailer re-engagement insights (Phase 9b, core, ADR-056): each shop's activity (last order, usual gap, orders and value over 90 days vs the 90 before) and segment (new, active, slowing, dormant, never ordered); a "Shop activity" screen and report, a dashboard tile "Shops to win back", call / WhatsApp / place an order / log a contact.
- Supplier bill photo → stock inward draft (OCR/LLM extraction, always human-confirmed).
- All AI calls go through `apps/ai` with provider abstraction, per-tenant usage tracking and limits, and no cross-tenant data in prompts.

### 5.16 Audit log
- Who, what (action code), target object, before/after diff for key fields, IP, user agent, timestamp, impersonation context. Viewable by tenant admin (own tenant) and super admin (all).

---


### 5.17 Global search (Phase 9a, ADR-053; always on)
- One search bar in the distributor panel and the super admin area: Ctrl/Cmd+K on laptops, a search icon opening a full-screen search on phones. Results as you type, grouped by type, keyboard navigation, and recent searches.
- Distributor: products (name, code, barcode), shops (name, owner, mobile, GSTIN), orders, invoices, credit notes, receipts, payments (reference, cheque number), refunds, goods receipts, adjustments, staff, suppliers and purchase orders, and pages and settings by name. Super admin: distributors (name, legal name, GSTIN, web address), platform pages and settings; users across distributors only through the audited path.
- A document number, GSTIN or 10-digit mobile goes straight to its match. Every result respects the user's permissions and the sales-visibility rule; results never show costs.
## 6. Data model outline (starting point, refine in Phase 0 plan)

Platform: `Tenant`, `TenantProfile`, `TenantSetting` (overrides of the settings registry), `PlatformSetting`, `TenantBranding`, `Plan`, `Subscription`, `FeatureFlag`, `TenantFeature`, `TaxRate`, `CessType`, `HsnRateHint`
Accounts: `User`, `Role`, `Permission`, `Membership` (user↔tenant↔role), `OTPRequest`, `Invitation`
Catalog: `Category`, `Brand`, `Unit`, `Product`, `ProductTaxRate` (effective-dated), `ProductImage`, `ProductBarcode`
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
Product variants, multi-currency, iOS app, marketplace across distributors, a single shared retailer account spanning multiple distributors (separate per-distributor accounts for the same mobile ARE supported), composition-scheme distributors / bill of supply, accounting software sync (Tally etc.), logistics partner APIs. Keep the design open to these.

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
Categories, brands, units, products (images, HSN, GST), bulk import/export, product search, retailers (CRUD, bulk import, welcome message via mock), price lists, retailer overrides, discount rules, `resolve_price` with full tests. Added at the end-of-phase review: discount combination modes, per-shop pricing tools (grid, copy, bulk %, report, pricing imports/exports), own-brand products and cost price.
**Accept when:** distributor imports 1,000 products and 100 retailers from Excel; a retailer logs in and sees only their distributor's products with correctly resolved prices.

### Phase 3 — Inventory
Default warehouse, stock levels, movement log, stock inward (with cost method and cost completion), adjustments, reorder levels, stock alerts (deduplicated), stock screens and reports (summary, movement history, low stock, valuation), barcode entry, availability labels for retailers.
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

### Phase 9 — Smart inventory, purchasing & AI (split, ADR-053)
- **9a** — global search; product stats (ABC, movement classes); suppliers and purchase orders; reorder suggestions.
- **9a+** — staging on AWS Mumbai for a pilot distributor (sandbox providers, test banner, pilot-ready seed, runbook).
- **9b** — re-engagement insights, daily owner summary, free-goods schemes.
- **9c** — delivery confirmation and code, shop return requests, cheque bounce charge.
- **9d** — AI foundation (provider abstraction, usage and limits) and semantic search.
- **9e** — distributor data assistant (tool calling over safe read-only functions, logged, with an evaluation set in CI).
- **After launch:** multi-warehouse and transfers, batches and expiry, manufacturing, demand forecasting, supplier-bill photo reading, convenience fee, own WhatsApp number and templates, saved filters and scheduled reports.
**Accept when:** each sub-phase is flag-gated where optional, tenant-scoped and independently mergeable; AI features are usage-tracked and degrade gracefully if the provider is down.

### Phase 10 — Hardening & launch
Hindi/Marathi translations, accessibility pass, performance/load testing, security review (dependency audit, permission review, pen-test checklist), backup-restore drill, runbooks, production deployment, subscription enforcement ready to switch on, the Platform Support role, and (with the CA review) the Tally export and the GSTR-1 JSON.

### Phase 11 — Android app
Expo app for retailers (and later distributor staff) using the generated API client: OTP login, catalog, cart, orders, invoices, payments, push notifications (FCM), tenant branding applied at runtime from the server. Single app on Play Store; branded builds per tenant as a future option.

---

## 13. Configurability principle

Business rules that are not firm are configurable; legal and data-integrity guarantees are fixed.

**Fixed in code (never configurable):**
- CGST+SGST vs IGST determination from the supplier state and place of supply.
- Gapless, per-financial-year invoice numbering, max 16 characters (the prefix/format is configurable, the rules are not).
- Issued invoices are immutable; corrections via credit notes.
- Ledger entries and stock movements are append-only.
- The credit exposure formula (ledger balance + open not-yet-invoiced orders + this order).
- Decimal money; every invoice reconciles to the paisa.

**Configurable:**
- **Platform level (super admin):** master GST rate table, cess types, optional HSN-to-rate mapping, default notification templates.
- **Product level:** GST rate and cess with effective-from dates.
- **Tenant level:** every setting in `docs/PLAN.md` §9 (Settings catalogue). Defaults:
  - prices GST-exclusive;
  - exact stock hidden; out-of-stock products shown as "Out of stock";
  - cost price updated by weighted average from goods receipts;
  - backorders on, with allocation confirmed by the distributor;
  - credit breach → approval;
  - invoice at dispatch;
  - rounding half-up to the paisa and nearest rupee;
  - Order Confirmation on acceptance on;
  - backorders billed at the original price;
  - staff can order on behalf;
  - sales staff see all orders;
  - holds reserve stock;
  - advances held;
  - cheques credited on receipt.

**Implementation requirements:**
- A typed settings registry in code: key, type, default, allowed values, scope (platform/tenant), permission required to edit, and a plain-language description. The settings UI is generated from the registry, grouped by area (Tax, Invoicing, Orders, Stock, Credit & Payments), with the description shown beside each setting.
- Orders, invoices and credit notes snapshot the settings in effect when they are created. Changing a setting later never alters existing documents.
- Every setting change is written to the audit log (who, old value, new value, when).
- Tax engine and order/credit tests cover every value of every relevant setting, not only the defaults.
- A newly created tenant works correctly without changing any setting.
