import { expect, test, type Browser, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import english from "../messages/en.json";
import hindi from "../messages/hi.json";
import marathi from "../messages/mr.json";
import { signInAsSuperAdmin } from "./support/flows";
import { ADMIN, FULL_STACK, OTP_CODE, manage, origin, resetLimits } from "./support/stack";

/**
 * Every screen at phone (360 px), tablet (768 px) and laptop (1440 px) width (CLAUDE.md
 * "Responsive design"), in one language: E2E_LANGUAGE (en, hi or mr; ADR-060 item 10, a CI job
 * each). The test accounts are signed in in English, then see the run's language, and are put
 * back to English at the end. Fails on:
 * - sideways scrolling of the page;
 * - buttons, links and fields that are off-screen (outside a scrollable strip) or overlap another
 *   one;
 * - touch targets smaller than 44 × 44 px at phone width (links inside running text excepted).
 * Saves a full-page screenshot of every screen at every width to test-results/responsive (a CI
 * artifact). Needs the full stack and `make seed` (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.skip(({ isMobile }) => isMobile, "sets its own widths");
test.describe.configure({ mode: "default", timeout: 900_000 });

const WIDTHS = [360, 768, 1440] as const;
const LANGUAGE = process.env.E2E_LANGUAGE ?? "en";
const CATALOGS = { en: english, hi: hindi, mr: marathi } as const;
const SEARCH_LABEL = (CATALOGS[LANGUAGE as keyof typeof CATALOGS] ?? english).search.label;
// English keeps its old place, so earlier screenshots still compare.
const SHOTS = join(
  __dirname,
  "..",
  "test-results",
  "responsive",
  ...(LANGUAGE === "en" ? [] : [LANGUAGE]),
);
const TEST_ACCOUNTS = ["--email", "owner@sharma.example.com", "--email", ADMIN.email];
const TEST_SHOPS = ["--phone", "9876500001"];

/** The run's language for the test accounts and shop (English puts them back). */
function speak(language: string) {
  manage(["e2e_language", language, ...TEST_ACCOUNTS, ...TEST_SHOPS]);
}

interface Ids {
  tenant: string;
  retailer: string;
  product: string;
  price_list: string;
  rule: string;
  import_job: string | null;
  receipt: string | null;
  draft_receipt: string | null;
  adjustment: string | null;
  shop_order: string | null;
  order: string | null;
  fulfilment: string | null;
  backorder_product: string | null;
  invoice: string | null;
  credit_note: string | null;
  payment: string | null;
  refund: string | null;
  shop_invoice: string | null;
  ewaybill_invoice: string | null;
  shop_checkout: string | null;
  supplier: string | null;
  purchase_order: string | null;
  draft_purchase_order: string | null;
  free_goods_scheme: string | null;
  return_request: string | null;
}

function pages(ids: Ids) {
  const staff = [
    "/manage",
    "/manage/orders",
    ...(ids.order ? [`/manage/orders/${ids.order}`] : []),
    "/manage/orders/shipments",
    "/manage/orders/new",
    "/manage/backorders",
    ...(ids.backorder_product ? [`/manage/backorders/${ids.backorder_product}`] : []),
    "/manage/invoices",
    ...(ids.invoice ? [`/manage/invoices/${ids.invoice}`] : []),
    "/manage/invoices/credit-notes",
    "/manage/invoices/credit-notes/new",
    ...(ids.invoice ? [`/manage/invoices/credit-notes/new?invoice=${ids.invoice}`] : []),
    ...(ids.credit_note ? [`/manage/invoices/credit-notes/${ids.credit_note}`] : []),
    "/manage/invoices/returns",
    ...(ids.return_request ? [`/manage/invoices/returns/${ids.return_request}`] : []),
    "/manage/invoices/einvoices",
    "/manage/invoices/ewaybills",
    ...(ids.ewaybill_invoice ? [`/manage/invoices/${ids.ewaybill_invoice}`] : []),
    "/manage/payments",
    "/manage/payments/new",
    `/manage/payments/new?retailer=${ids.retailer}`,
    ...(ids.payment ? [`/manage/payments/${ids.payment}`] : []),
    "/manage/payments/handover",
    "/manage/payments/online",
    "/manage/payments/refunds",
    "/manage/payments/refunds/new",
    ...(ids.refund ? [`/manage/payments/refunds/${ids.refund}`] : []),
    "/manage/receivables",
    `/manage/retailers/${ids.retailer}/ledger`,
    "/manage/settings/policies/invoicing",
    "/manage/settings/compliance",
    "/manage/settings/online-payments",
    "/manage/settings/policies/credit_payments",
    "/manage/products",
    "/manage/products/new",
    `/manage/products/${ids.product}`,
    "/manage/products/categories",
    "/manage/products/brands",
    "/manage/products/units",
    "/manage/retailers",
    "/manage/retailers/activity",
    "/manage/retailers/new",
    `/manage/retailers/${ids.retailer}`,
    `/manage/retailers/${ids.retailer}/discounts`,
    "/manage/imports",
    "/manage/imports/new",
    ...(ids.import_job ? [`/manage/imports/${ids.import_job}`] : []),
    "/manage/pricing/price-lists",
    `/manage/pricing/price-lists/${ids.price_list}`,
    "/manage/pricing/special-prices",
    "/manage/pricing/discounts",
    "/manage/pricing/discounts/new",
    `/manage/pricing/discounts/${ids.rule}`,
    "/manage/pricing/free-goods",
    "/manage/pricing/free-goods/new",
    ...(ids.free_goods_scheme ? [`/manage/pricing/free-goods/${ids.free_goods_scheme}`] : []),
    "/manage/pricing/report",
    "/manage/stock",
    `/manage/stock/${ids.product}`,
    "/manage/stock/movements",
    "/manage/stock/alerts",
    "/manage/stock/reorder",
    "/manage/stock/inwards",
    "/manage/stock/inwards/new",
    ...(ids.receipt ? [`/manage/stock/inwards/${ids.receipt}`] : []),
    ...(ids.draft_receipt ? [`/manage/stock/inwards/${ids.draft_receipt}`] : []),
    "/manage/stock/adjustments",
    "/manage/stock/adjustments/new",
    ...(ids.adjustment ? [`/manage/stock/adjustments/${ids.adjustment}`] : []),
    // Purchasing (ADR-053; Sharma has it on).
    "/manage/purchasing/orders",
    "/manage/purchasing/orders/new",
    ...(ids.purchase_order ? [`/manage/purchasing/orders/${ids.purchase_order}`] : []),
    ...(ids.draft_purchase_order
      ? [
          `/manage/purchasing/orders/${ids.draft_purchase_order}`,
          `/manage/purchasing/orders/${ids.draft_purchase_order}/edit`,
        ]
      : []),
    "/manage/purchasing/suppliers",
    "/manage/purchasing/suppliers/new",
    ...(ids.supplier ? [`/manage/purchasing/suppliers/${ids.supplier}`] : []),
    "/manage/purchasing/suppliers/from-receipts",
    "/manage/reports",
    "/manage/reports/low-stock",
    "/manage/reports/stock-valuation",
    "/manage/reports/exports",
    // Every report on the standard report screen (ADR-050): each lays its cards out differently.
    ...[
      "sales_summary",
      "sales_by_product",
      "sales_by_category",
      "sales_by_brand",
      "sales_by_shop",
      "sales_by_salesperson",
      "sales_by_invoice",
      "margin_own_vs_traded",
      "stock_summary",
      "stock_movements",
      "stock_movement_class",
      "backorder_demand",
      "fulfilment_rate",
      "receivables_ageing",
      "collections",
      "salesperson_collections",
      "gst_summary",
      "purchases_by_supplier",
    ].map((code) => `/manage/reports/${code}`),
    "/manage/assistant",
    "/manage/settings/business",
    "/manage/settings/branding",
    "/manage/settings/policies/tax",
    "/manage/settings/policies/pricing",
    "/manage/settings/policies/retailers",
    "/manage/settings/policies/stock",
    "/manage/settings/policies/reports",
    "/manage/settings/policies/planning",
    "/manage/settings/policies/purchasing",
    "/manage/settings/features",
    "/manage/settings/staff",
    "/manage/settings/roles",
    "/manage/audit",
    "/manage/account",
    "/manage/notifications",
    "/manage/settings/notifications",
    "/manage/settings/notifications/texts",
    "/manage/settings/notifications/deliveries",
    "/manage/settings/notifications/announcements",
    "/manage/settings/policies/notifications",
  ];
  const platform = [
    "/platform",
    "/platform/tenants",
    "/platform/tenants/new",
    `/platform/tenants/${ids.tenant}`,
    "/platform/plans",
    "/platform/feature-flags",
    "/platform/tax-rates",
    "/platform/settings",
    "/platform/impersonations",
    "/platform/notifications",
    "/platform/notifications/failures",
    "/platform/languages",
    "/platform/audit",
    "/platform/account",
  ];
  const shop = [
    "/shop",
    "/shop/catalog",
    "/shop/search?q=parle",
    `/shop/products/${ids.product}`,
    "/shop/cart",
    "/shop/orders",
    ...(ids.shop_order ? [`/shop/orders/${ids.shop_order}`] : []),
    "/shop/account",
    "/shop/account/security",
    "/shop/account/messages",
    "/shop/invoices",
    ...(ids.shop_invoice ? [`/shop/invoices/${ids.shop_invoice}`] : []),
    "/shop/statement",
    "/shop/payments",
    ...(ids.shop_checkout ? [`/shop/payments/checkout/${ids.shop_checkout}`] : []),
    "/shop/notifications",
  ];
  return { staff, platform, shop };
}

interface Problem {
  kind: string;
  what: string;
}

/** Runs in the page: the layout problems described above. */
function findProblems(phone: boolean): Problem[] {
  const vw = document.documentElement.clientWidth;
  const problems: Problem[] = [];
  if (document.documentElement.scrollWidth > vw + 1) {
    problems.push({
      kind: "sideways-scroll",
      what: `page is ${document.documentElement.scrollWidth}px wide in a ${vw}px window`,
    });
  }
  const selector = [
    "a[href]",
    "button",
    "input:not([type=hidden])",
    "select",
    "textarea",
    "[role=button]",
    "[role=combobox]",
    "[role=checkbox]",
    "[role=switch]",
    "[role=radio]",
  ].join(",");
  const describe = (el: Element) => {
    const name = (
      el.getAttribute("aria-label") ||
      (el as HTMLElement).innerText ||
      el.getAttribute("placeholder") ||
      el.getAttribute("name") ||
      ""
    )
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 40);
    return `${el.tagName.toLowerCase()}${el.getAttribute("role") ? `[${el.getAttribute("role")}]` : ""} "${name}"`;
  };
  const ancestors = (el: Element) => {
    const list: Element[] = [];
    for (let p = el.parentElement; p; p = p.parentElement) list.push(p);
    return list;
  };
  const visible = Array.from(document.querySelectorAll(selector)).filter((el) => {
    if (el.closest("[aria-hidden=true], [hidden], [inert], .sr-only")) return false;
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0")
      return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2; // sr-only elements are 1 px
  });
  const pinned = (el: Element) =>
    [el, ...ancestors(el)].some((a) => ["fixed", "sticky"].includes(getComputedStyle(a).position));
  const inScroller = (el: Element) =>
    ancestors(el).some((a) => ["auto", "scroll"].includes(getComputedStyle(a).overflowX));

  for (const el of visible) {
    const r = el.getBoundingClientRect();
    if ((r.left < -1 || r.right > vw + 1) && !inScroller(el)) {
      problems.push({ kind: "off-screen", what: `${describe(el)} at x=${Math.round(r.left)}` });
    }
    if (phone) {
      const style = getComputedStyle(el);
      const inlineText = style.display === "inline" && el.tagName === "A";
      if (!inlineText) {
        // A radio or checkbox inside a label: the whole label is the target.
        const label = el.closest("label");
        const labelled = Boolean(label && /^(input|button)$/i.test(el.tagName));
        const box = labelled ? label!.getBoundingClientRect() : r;
        // Hit areas grown with a ::after pseudo-element (checkboxes, switches) count.
        const after = getComputedStyle(el, "::after");
        const grow = (v: string) => (v.endsWith("px") && parseFloat(v) < 0 ? -parseFloat(v) : 0);
        const absolute = after.position === "absolute" && after.content !== "none";
        const width = Math.max(
          box.width,
          r.width + (absolute ? grow(after.left) + grow(after.right) : 0),
        );
        const height = Math.max(
          box.height,
          r.height + (absolute ? grow(after.top) + grow(after.bottom) : 0),
        );
        if (width < 43.5 || height < 43.5) {
          problems.push({
            kind: "small-target",
            what: `${describe(el)} is ${Math.round(width)}×${Math.round(height)}px`,
          });
        }
      }
    }
  }
  // Overlapping controls (in the normal page flow; fixed and sticky bars cover content by design
  // and scrolling reveals it).
  const flow = visible.filter((el) => !pinned(el));
  for (let i = 0; i < flow.length; i++) {
    for (let j = i + 1; j < flow.length; j++) {
      const a = flow[i]!;
      const b = flow[j]!;
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      const x = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const y = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (x > 2 && y > 2) {
        problems.push({ kind: "overlap", what: `${describe(a)} overlaps ${describe(b)}` });
      }
    }
  }
  return problems;
}

/** Locally, `E2E_ONLY=reports,=/manage` checks just some screens: those whose path contains an
 * entry, or equals one written with `=`. */
const ONLY = (process.env.E2E_ONLY ?? "").split(",").filter(Boolean);
const wanted = (path: string) =>
  !ONLY.length ||
  ONLY.some((entry) => (entry.startsWith("=") ? path === entry.slice(1) : path.includes(entry)));

async function sweep(page: Page, base: string, all: string[], width: number, area: string) {
  const paths = all.filter(wanted);
  const found: string[] = [];
  const dir = join(SHOTS, String(width));
  mkdirSync(dir, { recursive: true });
  for (const path of paths) {
    await page.goto(`${base}${path}`);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await page.waitForTimeout(400); // images and late layout
    const problems = await page.evaluate(findProblems, width < 768);
    for (const p of problems) found.push(`${width}px ${area}${path}: ${p.kind}: ${p.what}`);
    const name = `${area}${path}`
      .replace(/#.*/, "") // a one-time code
      .replace(/[/?=]+/g, "_")
      .replace(/_$/, "");
    await page.screenshot({ path: join(dir, `${name}.png`), fullPage: true });
  }
  return found;
}

/** Global search (ADR-053), open with results: full screen on phones, a dialog elsewhere. */
async function searchOpen(page: Page, base: string, width: number, area: string, text: string) {
  if (!wanted("search")) return [];
  await page.goto(`${base}${area === "platform" ? "/platform" : "/manage"}`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.keyboard.press("Control+K");
  await page.getByRole("combobox", { name: SEARCH_LABEL }).fill(text);
  await page.getByRole("option").first().waitFor();
  await page.waitForTimeout(300);
  const problems = await page.evaluate(findProblems, width < 768);
  await page.screenshot({ path: join(SHOTS, String(width), `${area}_search.png`) });
  await page.keyboard.press("Escape");
  return problems.map((p) => `${width}px ${area} search: ${p.kind}: ${p.what}`);
}

async function staffPage(browser: Browser, width: number) {
  resetLimits({ emails: ["owner@sharma.example.com"] });
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${origin("sharma")}/login`);
  await page.getByLabel(/email address/i).fill("owner@sharma.example.com");
  await page.getByLabel(/^password/i).fill("staff-dev-password");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${origin("sharma")}/manage`);
  return { context, page };
}

async function shopPage(browser: Browser, width: number) {
  resetLimits({ phones: ["9876500001"] });
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${origin("sharma")}/shop/login`);
  await page.getByLabel(/mobile number/i).fill("9876500001");
  await page.getByRole("button", { name: /send code/i }).click();
  await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${origin("sharma")}/shop`);
  return { context, page };
}

// English again for the other suites, even when a run fails half way.
test.afterAll(() => {
  if (LANGUAGE !== "en") speak("en");
});

for (const width of WIDTHS) {
  test(`every screen at ${width}px`, async ({ browser }) => {
    const ids = JSON.parse(manage(["e2e_ids"]).trim().split("\n").pop()!) as Ids;
    const { staff, platform, shop } = pages(ids);
    const problems: string[] = [];

    speak(LANGUAGE);
    const publicContext = await browser.newContext({ viewport: { width, height: 900 } });
    await publicContext.addCookies(
      ["sharma", "", "admin"].map((slug) => ({
        name: "NEXT_LOCALE",
        value: LANGUAGE,
        url: origin(slug || undefined),
      })),
    );
    const publicPage = await publicContext.newPage();
    problems.push(
      ...(await sweep(publicPage, origin("sharma"), ["/login", "/shop/login"], width, "public")),
      ...(await sweep(publicPage, origin(), ["/login"], width, "public-main")),
      ...(await sweep(publicPage, origin("admin"), ["/login"], width, "public-admin")),
    );
    await publicContext.close();

    const s = await staffPage(browser, width);
    problems.push(...(await sweep(s.page, origin("sharma"), staff, width, "staff")));
    problems.push(...(await searchOpen(s.page, origin("sharma"), width, "staff", "ganesh")));
    await s.context.close();

    const adminContext = await browser.newContext({ viewport: { width, height: 900 } });
    const admin = await adminContext.newPage();
    await signInAsSuperAdmin(admin);
    problems.push(...(await sweep(admin, origin("admin"), platform, width, "platform")));
    problems.push(...(await searchOpen(admin, origin("admin"), width, "platform", "sharma")));
    await adminContext.close();

    const r = await shopPage(browser, width);
    problems.push(...(await sweep(r.page, origin("sharma"), shop, width, "shop")));
    await r.context.close();

    // The Android app's browser payment page (ADR-061 item 9), opened by a one-time link.
    const pay = new URL(JSON.parse(manage(["e2e_pay_link"]).trim().split("\n").pop()!).url);
    const payContext = await browser.newContext({ viewport: { width, height: 900 } });
    await payContext.addCookies([{ name: "NEXT_LOCALE", value: LANGUAGE, url: origin("sharma") }]);
    const payPage = await payContext.newPage();
    problems.push(
      ...(await sweep(payPage, origin("sharma"), [`${pay.pathname}${pay.hash}`], width, "pay")),
    );
    await payContext.close();

    expect(problems, problems.join("\n")).toEqual([]);
  });
}
