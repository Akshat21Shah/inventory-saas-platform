# Phase Prompts — paste these into the agent one at a time

## Setup (do this once)
1. Create an empty Git repository.
2. Put `CLAUDE.md` in the repo root and `PROJECT_SPEC.md` + this file in `/docs`.
3. Create empty `docs/PROGRESS.md` and `docs/DECISIONS.md`.
4. Start the agent in the repo root and use the prompts below in order. Review and commit after every phase.

---

## Prompt 0 — Kickoff and master plan

```
Read CLAUDE.md and docs/PROJECT_SPEC.md completely before doing anything.

You are the lead engineer building this platform from scratch. Do not write any code yet.

Produce docs/PLAN.md containing:
1. Your understanding of the product in 10 lines, and a list of every ambiguity or risk you see in the spec (especially around money, GST, stock, backorders and tenant isolation), each with your recommended resolution.
2. The complete data model: every model with fields, types, constraints, indexes and relationships, grouped by Django app. Include an ER diagram in Mermaid.
3. The full REST API surface for v1: endpoint, method, permission code, purpose, grouped by module.
4. The order, backorder, invoice, ledger and payment state machines with every transition, who can trigger it, and the side effects.
5. The stock reservation and backorder allocation algorithm in pseudocode, including locking order.
6. The tax calculation algorithm with worked examples (intra-state, inter-state, discount, mixed rates, rounding).
7. The frontend route map for platform admin, distributor panel and retailer app, with the main components per screen.
8. For each roadmap phase: the task breakdown, in order, with estimated size (S/M/L).

Stop after writing the plan and list the questions you need me to answer.
```

---

## Prompt 1 — Phase 0: Foundation

```
Read CLAUDE.md, docs/PROJECT_SPEC.md, docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 0 (Foundation) exactly as defined in PROJECT_SPEC.md section 12.

Requirements:
- Monorepo with /backend, /web, /infra, /docs. Docker Compose with postgres, redis, mailpit, backend (ASGI), celery worker, celery beat, web.
- Django: settings split (base/dev/test/prod) via environment variables, DRF, drf-spectacular, Celery, Channels, CORS, JWT auth scaffolding, structured JSON logging with request_id and tenant_id, Sentry, health endpoints (/health/live, /health/ready).
- common app: TimeStampedModel, TenantScopedModel + tenant-aware manager, tenant context variable, middleware, RLS helper + migration pattern, standard error response format with error codes, pagination, base permission classes, Decimal money helpers.
- Next.js (App Router, TypeScript strict): Tailwind, shadcn/ui, design tokens as CSS variables (supporting per-tenant brand colour), light theme, layout shells for (platform), (distributor), (retailer), next-intl with en.json, TanStack Query provider, generated API client pipeline (make api-client), shared components: DataTable, EmptyState, ErrorState, PageHeader, StatusBadge, MoneyText (INR format), ConfirmDialog, skeletons. A /design-system page showcasing all of them.
- PWA basics for the retailer area (manifest, icons placeholder, offline fallback).
- Tooling: ruff, mypy, pytest (+ pytest-django, factory_boy), eslint, prettier, vitest, Playwright skeleton, pre-commit, Makefile targets from CLAUDE.md, GitHub Actions CI.

Show me the plan first, then implement. Finish by running everything, confirming the acceptance criteria, and updating docs/PROGRESS.md.
```

---

## Prompt 2 — Phase 1: Tenancy, auth, platform admin

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 2, 4.2, 5.1–5.3, 5.16), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 1: tenants and onboarding wizard, feature flags, plans with enforcement OFF (Beta plan default), users/roles/permissions (permission codes grouped into roles, per the matrix), staff email+password auth with TOTP 2FA (mandatory for super admin), retailer mobile OTP auth with a mock SMS adapter (fixed OTP in dev), JWT access + httpOnly refresh cookie, rate limiting, staff invitations, tenant branding and settings (distributor admin only), super admin panel (tenant list/detail/create/suspend, feature flags, impersonation with reason + banner + audit), and the audit log.

Frontend: login screens (staff and retailer OTP), super admin area, distributor settings/branding/staff screens, tenant branding applied via CSS variables.

Tests must include a tenant isolation test for every new endpoint and permission tests for each role. Plan first, then implement, verify acceptance criteria, update docs.
```

---

## Prompt 3 — Phase 2: Catalog, retailers, pricing

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 5.4–5.6), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 2: categories (3 levels), brands, units with pack conversion, products (images with resizing to S3-compatible storage, HSN, GST rate, MRP, base price, min qty, multiples), Excel/CSV bulk import with row-level validation report and templates, export, product search (full-text + trigram, < 200 ms on 20k products), retailers (CRUD, GSTIN validation, bulk import, welcome notification via mock), price lists, retailer price overrides, discount rules with slabs and validity, and pricing.services.resolve_price exactly per section 5.6 with exhaustive unit tests.

Frontend: distributor product/category/retailer/pricing screens with tables, filters, bulk actions and import wizard; retailer catalog browsing (read-only for now) showing resolved prices.

Seed command: 2 distributors, 200 products each, 20 retailers each, price lists and discounts. Plan first, then implement, verify, update docs.
```

---

## Prompt 4 — Phase 3: Inventory

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (section 5.7), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 3: default warehouse per tenant, StockLevel with DB check constraints, append-only StockMovement, inventory services (all changes inside transaction.atomic with select_for_update in consistent lock order), stock inward entry, adjustments with mandatory reasons (audited), reorder levels, deduplicated stock alerts (LOW_STOCK, OUT_OF_STOCK, BACKORDER_DEMAND) emitted as domain events, availability labels for retailers respecting the "show exact quantity" setting.

Frontend: stock overview, product stock detail with movement history, inward entry form (fast keyboard entry + barcode input), adjustments, alerts list, low stock report.

Include a real concurrency test (parallel threads/transactions) proving stock can never go negative or be double-reserved. Plan first, then implement, verify, update docs.
```

---

## Prompt 5 — Phase 4: Ordering and backorders

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 5.8, 5.9, 8), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 4:
- Server-side cart with resolved prices, tax estimate, availability and backorder split per line.
- Idempotent order placement service exactly per section 5.8 (reservation, backorder split, validations, credit check stub, order numbering, price snapshots, OrderPlaced event on commit).
- Order state machine with status history; distributor accept / reject / modify-before-accept / pack / dispatch / deliver; retailer cancel before acceptance; reservations released correctly on reject/cancel.
- Backorder queue grouped by product (oldest first) and allocation on stock inward (auto or suggest-and-confirm per tenant setting).
- Real-time push via Channels to the distributor (new orders, status changes) and to the retailer (status changes).

Frontend — this is the most important UX in the product:
- Retailer PWA: bottom navigation, home (search, categories, repeat last order, recent orders), fast search, product cards with image, price and availability badge, quantity stepper respecting min/multiples, cart with backorder lines clearly separated and explained in plain language, one-screen checkout, order confirmation, order list and detail with status timeline. Must feel effortless on a 360px Android screen.
- Distributor: orders board with tabs (New, On hold, Backorders, In progress, Completed), live new-order toast + sound option, order detail with accept/reject/modify, backorder queue and allocation screen.

Write the Playwright E2E test described in the Phase 4 acceptance criteria. Plan first, then implement, verify, update docs.
```

---

## Prompt 6 — Phase 5: Billing, GST, ledger, credit control

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 5.10, 5.12 offline part), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 5: invoice series per tenant per financial year (gapless, locked sequence, max 16 chars), tax engine in billing/tax.py (CGST+SGST vs IGST by place of supply, per-line tax on post-discount taxable value, round-off line) with exhaustive tests including worked examples from PLAN.md, invoice generation on acceptance and on backorder allocation, async PDF generation to storage with signed URLs, credit notes, append-only retailer ledger with running balance, offline payment recording (cash/cheque/bank/UPI-offline) with FIFO or manual allocation, outstanding and ageing, receipts, and real credit limit enforcement (BLOCK or REQUIRE_APPROVAL → ON_HOLD with approve/reject).

Frontend: invoice list/detail/PDF, credit notes, retailer ledger statement, record payment, receivables ageing, credit hold approvals; retailer screens for invoices, ledger and outstanding.

Add a reconciliation test: for random generated scenarios, ledger balance == invoices − payments − credit notes. Plan first, then implement, verify, update docs.
```

---

## Prompt 7 — Phase 6: Notifications

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (section 5.13), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 6: notification service subscribed to domain events, per-tenant event→recipient→channel rules with defaults, templates (platform defaults + tenant overrides, WhatsApp template name + variables), channels: in-app (notification centre + real-time badge), email (mock in dev, SES adapter), WhatsApp (mock + provider adapter), SMS (OTP only); delivery log with attempts, retries with backoff, failure visibility for tenant admin and super admin; scheduled payment reminders for overdue invoices; retailer notification preferences. Invoice notifications include a secure PDF link.

Plan first, then implement, verify every key event end to end with the mock adapters, update docs.
```

---

## Prompt 8 — Phase 7: E-invoice, e-way bill, online payments

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 5.11, 5.12 online part, 10), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 7, everything behind tenant feature flags (default OFF):
- compliance app: GSP adapter interface + mock; e-invoice IRN generation (async, retries, status visible), IRN + signed QR on invoice PDF, cancellation within the allowed window; e-way bill generation with transport details and Part-B update. Encrypted per-tenant GST credentials.
- payments app: gateway adapter interface; Razorpay implementation using sandbox keys; tenant key onboarding (encrypted); retailer checkout for an invoice / full outstanding / custom amount; payment confirmation ONLY via signature-verified webhooks, stored WebhookEvent for idempotency; periodic reconciliation job; ledger credit and receipts.

Do not invent API field names — where you are unsure, implement against the adapter interface, leave a clearly marked TODO listing exactly what must be verified in official docs, and tell me. Confirm the app behaves identically with flags off. Plan first, then implement, verify, update docs.
```

---

## Prompt 9 — Phase 8: Dashboards and reports

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (section 5.14), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 8: distributor "action today" dashboard, the complete report list from section 5.14 with filters and Excel/PDF export (heavy reports generated async with a download notification), GST summary reports (B2B invoice-wise, HSN summary), and the super admin platform dashboard.

Extend the seed command to generate 50,000 orders across tenants and verify performance targets from section 7. Add indexes or materialised summaries where needed and document them. Plan first, then implement, verify, update docs.
```

---

## Prompt 10 — Phase 9: Smart inventory and AI

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (section 5.15), docs/PLAN.md and docs/PROGRESS.md.

Implement Phase 9, all behind tenant feature flags:
- Reorder suggestions (sales velocity, lead time, safety stock) with explanations the distributor can understand.
- ABC analysis and fast/slow/dead stock classification (scheduled jobs).
- Semantic product search with pgvector embeddings, tolerant of typos and Hindi/English mix, falling back to normal search if unavailable.
- Distributor data assistant: LLM with tool calling over a fixed set of safe, tenant-scoped, read-only query functions (never model-written SQL), with per-tenant usage tracking and limits.
- Dormant/declining retailer insights.
- apps/ai provider abstraction; everything must degrade gracefully when the AI provider is down.

Plan first (including prompt designs and tool definitions), then implement, verify, update docs.
```

---

## Prompt 11 — Phase 10: Hardening and launch

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (sections 7–9, 12 Phase 10), docs/PLAN.md and docs/PROGRESS.md.

Perform Phase 10:
1. Add Hindi and Marathi translation files for all keys; verify layouts don't break.
2. Accessibility audit and fixes.
3. Load test (e.g. Locust/k6) the ordering and search flows at target scale; fix bottlenecks.
4. Security review: dependency audit, permission matrix review against code, tenant isolation test coverage report, OWASP checklist, secrets handling, headers.
5. Backup and restore drill documented in docs/RUNBOOKS.md, plus runbooks for common incidents.
6. Production deployment configuration for AWS Mumbai with zero-downtime deploys.
7. Verify subscription enforcement can be switched on safely.

Report findings with severity before fixing, then fix, verify, update docs.
```

---

## Prompt 12 — Phase 11: Android app

```
Read CLAUDE.md, docs/PROJECT_SPEC.md (section 12 Phase 11), docs/PLAN.md and docs/PROGRESS.md.

Build the retailer Android app in /mobile with React Native (Expo) + TypeScript, reusing the generated API client and design tokens. Screens mirror the retailer PWA: OTP login, home, search, catalog, product, cart, checkout, orders with timeline, invoices (view/share PDF), ledger, payments (if enabled), notifications, profile, language switch. Tenant branding loaded from the server at runtime. Push notifications via FCM (register device tokens with the backend). Secure token storage. Handle poor connectivity gracefully (cached catalog, retry, clear offline messages).

Plan first, then implement, verify on an emulator, and prepare a Play Store release build checklist.
```

---

## Utility prompts (use any time)

**Resume after a break**
```
Read CLAUDE.md, docs/PROGRESS.md and docs/PLAN.md. Summarise where we are, what is in progress, and propose the next 3 tasks. Wait for my go-ahead.
```

**Fix a bug properly**
```
Bug: <describe what happened, steps, expected vs actual>.
First reproduce it with a failing test. Then find the root cause (explain it), fix it, confirm the test passes and nothing else broke. Check whether the same bug pattern exists elsewhere.
```

**Code review of the last phase**
```
Review all changes from the current phase as a strict senior reviewer. Check: tenant isolation, permission checks, transactions and locking, Decimal usage, idempotency, N+1 queries, missing indexes, error handling, test coverage of edge cases, UX states, i18n. List findings by severity, then fix them.
```

**Add a new feature later**
```
New feature request: <describe>. Read CLAUDE.md and PROJECT_SPEC.md. First update PROJECT_SPEC.md with the feature spec and PLAN.md with the design, flag any impact on existing modules, and wait for approval before implementing.
```
