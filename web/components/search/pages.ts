/**
 * Pages and settings global search finds by name (ADR-053): matched here, in the browser, from
 * their translated names and extra search words (`search.keywords.<key>`, the words distributors
 * use: "dues", "bills", "GST rates"…); records come from the server. Only what the person may
 * open is offered (the server still guards every page).
 */

export interface Destination {
  /** Key under "search.pages" (pages), or the full message key of a setting's label. */
  key: string;
  href: string;
  /** Any one of these permissions (none: every staff member). */
  permission?: string | string[];
  /** An optional module that must be on. */
  feature?: string;
}

export const STAFF_PAGES: Destination[] = [
  { key: "dashboard", href: "/manage" },
  { key: "orders", href: "/manage/orders", permission: "orders.view" },
  { key: "newOrder", href: "/manage/orders/new", permission: "orders.create_on_behalf" },
  { key: "shipments", href: "/manage/orders/shipments", permission: "orders.view" },
  { key: "backorders", href: "/manage/backorders", permission: "orders.view" },
  { key: "products", href: "/manage/products", permission: "products.view" },
  { key: "newProduct", href: "/manage/products/new", permission: "products.manage" },
  { key: "categories", href: "/manage/products/categories", permission: "products.view" },
  { key: "brands", href: "/manage/products/brands", permission: "products.view" },
  { key: "units", href: "/manage/products/units", permission: "products.view" },
  { key: "retailers", href: "/manage/retailers", permission: "retailers.view" },
  { key: "newRetailer", href: "/manage/retailers/new", permission: "retailers.manage" },
  { key: "priceLists", href: "/manage/pricing/price-lists", permission: "pricing.view" },
  { key: "discounts", href: "/manage/pricing/discounts", permission: "pricing.view" },
  { key: "specialPrices", href: "/manage/pricing/special-prices", permission: "pricing.view" },
  { key: "stock", href: "/manage/stock", permission: "stock.view" },
  {
    key: "purchaseOrders",
    href: "/manage/purchasing/orders",
    permission: "purchasing.view",
    feature: "purchasing",
  },
  {
    key: "newPurchaseOrder",
    href: "/manage/purchasing/orders/new",
    permission: "purchasing.manage",
    feature: "purchasing",
  },
  {
    key: "suppliers",
    href: "/manage/purchasing/suppliers",
    permission: "purchasing.view",
    feature: "purchasing",
  },
  {
    key: "newSupplier",
    href: "/manage/purchasing/suppliers/new",
    permission: "purchasing.manage",
    feature: "purchasing",
  },
  {
    key: "suppliersFromReceipts",
    href: "/manage/purchasing/suppliers/from-receipts",
    permission: "purchasing.manage",
    feature: "purchasing",
  },
  {
    key: "goodsReceipts",
    href: "/manage/stock/inwards",
    permission: ["stock.inward", "costs.view"],
  },
  { key: "newGoodsReceipt", href: "/manage/stock/inwards/new", permission: "stock.inward" },
  { key: "adjustments", href: "/manage/stock/adjustments", permission: "stock.adjust" },
  { key: "stockAlerts", href: "/manage/stock/alerts", permission: "stock.view" },
  {
    key: "reorderSuggestions",
    href: "/manage/stock/reorder",
    permission: ["purchasing.view", "stock.view"],
    feature: "stock_planning",
  },
  { key: "movements", href: "/manage/stock/movements", permission: "stock.view" },
  { key: "invoices", href: "/manage/invoices", permission: "invoices.view" },
  { key: "creditNotes", href: "/manage/invoices/credit-notes", permission: "invoices.view" },
  {
    key: "einvoices",
    href: "/manage/invoices/einvoices",
    permission: "compliance.manage",
    feature: "einvoice",
  },
  {
    key: "ewaybills",
    href: "/manage/invoices/ewaybills",
    permission: "compliance.manage",
    feature: "ewaybill",
  },
  { key: "payments", href: "/manage/payments", permission: "payments.view" },
  { key: "newPayment", href: "/manage/payments/new", permission: "payments.record" },
  { key: "refunds", href: "/manage/payments/refunds", permission: "payments.view" },
  {
    key: "handover",
    href: "/manage/payments/handover",
    permission: ["payments.record", "payments.collect"],
  },
  { key: "receivables", href: "/manage/receivables", permission: "ledger.view" },
  { key: "reports", href: "/manage/reports" },
  { key: "myExports", href: "/manage/reports/exports" },
  {
    key: "imports",
    href: "/manage/imports",
    permission: ["products.manage", "retailers.manage", "pricing.manage", "stock.adjust"],
  },
  { key: "messages", href: "/manage/notifications" },
  { key: "account", href: "/manage/account" },
  { key: "audit", href: "/manage/audit", permission: "audit.view" },
  { key: "businessDetails", href: "/manage/settings/business" },
  { key: "branding", href: "/manage/settings/branding" },
  { key: "staff", href: "/manage/settings/staff", permission: "staff.manage" },
  { key: "roles", href: "/manage/settings/roles", permission: "staff.manage" },
  { key: "modules", href: "/manage/settings/features" },
  {
    key: "onlinePayments",
    href: "/manage/settings/online-payments",
    permission: "settings.manage",
    feature: "payments",
  },
  {
    key: "messageRules",
    href: "/manage/settings/notifications",
    permission: "notifications.manage",
  },
  {
    key: "messageTexts",
    href: "/manage/settings/notifications/texts",
    permission: "notifications.manage",
  },
  {
    key: "deliveryLog",
    href: "/manage/settings/notifications/deliveries",
    permission: "notifications.manage",
  },
  {
    key: "announcements",
    href: "/manage/settings/notifications/announcements",
    permission: "notifications.manage",
  },
  // Each settings group as a page, so "tax settings" or "GST" finds it.
  { key: "taxSettings", href: "/manage/settings/policies/tax" },
  { key: "invoicingSettings", href: "/manage/settings/policies/invoicing" },
  { key: "orderSettings", href: "/manage/settings/policies/orders" },
  { key: "pricingSettings", href: "/manage/settings/policies/pricing" },
  { key: "retailerSettings", href: "/manage/settings/policies/retailers" },
  { key: "stockSettings", href: "/manage/settings/policies/stock" },
  { key: "creditSettings", href: "/manage/settings/policies/credit_payments" },
  { key: "reportSettings", href: "/manage/settings/policies/reports" },
  {
    key: "planningSettings",
    href: "/manage/settings/policies/planning",
    feature: "stock_planning",
  },
  {
    key: "purchasingSettings",
    href: "/manage/settings/policies/purchasing",
    feature: "purchasing",
  },
  { key: "securitySettings", href: "/manage/settings/policies/security" },
];

export const PLATFORM_PAGES: Destination[] = [
  { key: "platformDashboard", href: "/platform" },
  { key: "distributors", href: "/platform/tenants", permission: "platform.tenants.manage" },
  {
    key: "newDistributor",
    href: "/platform/tenants/new",
    permission: "platform.tenants.manage",
  },
  { key: "plans", href: "/platform/plans", permission: "platform.plans.manage" },
  { key: "featureFlags", href: "/platform/feature-flags", permission: "platform.flags.manage" },
  { key: "taxRates", href: "/platform/tax-rates", permission: "platform.settings.manage" },
  {
    key: "platformSettings",
    href: "/platform/settings",
    permission: "platform.settings.manage",
  },
  { key: "platformAudit", href: "/platform/audit" },
  { key: "supportSessions", href: "/platform/impersonations" },
  { key: "failedMessages", href: "/platform/notifications/failures" },
  { key: "account", href: "/platform/account" },
];

/**
 * Where a distributor setting is edited, by the first part of its key (`planning.demand_days`
 * → the Stock planning group). Settings of an optional module only while it is on.
 */
export const SETTING_PAGES: Record<string, { href: string; feature?: string }> = {
  tax: { href: "/manage/settings/policies/tax" },
  invoicing: { href: "/manage/settings/policies/invoicing" },
  orders: { href: "/manage/settings/policies/orders" },
  backorders: { href: "/manage/settings/policies/stock" },
  stock: { href: "/manage/settings/policies/stock" },
  credit: { href: "/manage/settings/policies/credit_payments" },
  payments: { href: "/manage/settings/policies/credit_payments" },
  receivables: { href: "/manage/settings/policies/credit_payments" },
  pricing: { href: "/manage/settings/policies/pricing" },
  retailers: { href: "/manage/settings/policies/retailers" },
  reports: { href: "/manage/settings/policies/reports" },
  security: { href: "/manage/settings/policies/security" },
  notifications: { href: "/manage/settings/policies/notifications" },
  einvoice: { href: "/manage/settings/compliance", feature: "einvoice" },
  ewaybill: { href: "/manage/settings/compliance", feature: "ewaybill" },
  planning: { href: "/manage/settings/policies/planning", feature: "stock_planning" },
  purchasing: { href: "/manage/settings/policies/purchasing", feature: "purchasing" },
};

/** Lower case, accents and extra spaces ignored, for matching typed words against names. */
export function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** Every typed word appears in the name, as a word start ("pur ord" finds "Purchase orders"). */
export function matches(name: string, query: string): boolean {
  const words = fold(name).split(/[^\p{L}\p{N}]+/u);
  return fold(query)
    .split(" ")
    .filter(Boolean)
    .every((typed) => words.some((word) => word.startsWith(typed)));
}

/**
 * How well a page answers what was typed, best first: its name (4), one of its search words
 * exactly as typed (3: "rates" is a price list's word, before "GST rates" of products), every
 * typed word in one search word (2), or across them (1). 0: not a match. `keywords` is the
 * comma-separated `search.keywords.<key>` message.
 */
export function rank(name: string, keywords: string, query: string): number {
  if (matches(name, query)) return 4;
  const phrases = keywords.split(",").map(fold).filter(Boolean);
  if (!phrases.length) return 0;
  const typed = fold(query);
  if (phrases.includes(typed)) return 3;
  if (phrases.some((phrase) => matches(phrase, typed))) return 2;
  return matches(phrases.join(" "), typed) ? 1 : 0;
}
