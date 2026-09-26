import { expect, test, type Browser, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { signInAsSuperAdmin } from "./support/flows";
import { FULL_STACK, OTP_CODE, manage, origin, resetLimits } from "./support/stack";

/**
 * Every screen at phone (360 px), tablet (768 px) and laptop (1440 px) width (CLAUDE.md
 * "Responsive design"). Fails on:
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
const SHOTS = join(__dirname, "..", "test-results", "responsive");

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
}

function pages(ids: Ids) {
  const staff = [
    "/manage",
    "/manage/products",
    "/manage/products/new",
    `/manage/products/${ids.product}`,
    "/manage/products/categories",
    "/manage/products/brands",
    "/manage/products/units",
    "/manage/retailers",
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
    "/manage/pricing/report",
    "/manage/stock",
    `/manage/stock/${ids.product}`,
    "/manage/stock/movements",
    "/manage/stock/alerts",
    "/manage/stock/inwards",
    "/manage/stock/inwards/new",
    ...(ids.receipt ? [`/manage/stock/inwards/${ids.receipt}`] : []),
    ...(ids.draft_receipt ? [`/manage/stock/inwards/${ids.draft_receipt}`] : []),
    "/manage/stock/adjustments",
    "/manage/stock/adjustments/new",
    ...(ids.adjustment ? [`/manage/stock/adjustments/${ids.adjustment}`] : []),
    "/manage/reports",
    "/manage/reports/low-stock",
    "/manage/reports/stock-valuation",
    "/manage/settings/business",
    "/manage/settings/branding",
    "/manage/settings/policies/tax",
    "/manage/settings/policies/pricing",
    "/manage/settings/policies/retailers",
    "/manage/settings/policies/stock",
    "/manage/settings/features",
    "/manage/settings/staff",
    "/manage/settings/roles",
    "/manage/audit",
    "/manage/account",
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
    "/platform/audit",
    "/platform/account",
  ];
  const shop = [
    "/shop",
    "/shop/catalog",
    "/shop/search?q=parle",
    `/shop/products/${ids.product}`,
    "/shop/account",
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

async function sweep(page: Page, base: string, paths: string[], width: number, area: string) {
  const found: string[] = [];
  const dir = join(SHOTS, String(width));
  mkdirSync(dir, { recursive: true });
  for (const path of paths) {
    await page.goto(`${base}${path}`);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await page.waitForTimeout(400); // images and late layout
    const problems = await page.evaluate(findProblems, width < 768);
    for (const p of problems) found.push(`${width}px ${area}${path}: ${p.kind}: ${p.what}`);
    const name = `${area}${path}`.replace(/[/?=]+/g, "_").replace(/_$/, "");
    await page.screenshot({ path: join(dir, `${name}.png`), fullPage: true });
  }
  return found;
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

for (const width of WIDTHS) {
  test(`every screen at ${width}px`, async ({ browser }) => {
    const ids = JSON.parse(manage(["e2e_ids"]).trim().split("\n").pop()!) as Ids;
    const { staff, platform, shop } = pages(ids);
    const problems: string[] = [];

    const publicContext = await browser.newContext({ viewport: { width, height: 900 } });
    const publicPage = await publicContext.newPage();
    problems.push(
      ...(await sweep(publicPage, origin("sharma"), ["/login", "/shop/login"], width, "public")),
      ...(await sweep(publicPage, origin(), ["/login"], width, "public-main")),
      ...(await sweep(publicPage, origin("admin"), ["/login"], width, "public-admin")),
    );
    await publicContext.close();

    const s = await staffPage(browser, width);
    problems.push(...(await sweep(s.page, origin("sharma"), staff, width, "staff")));
    await s.context.close();

    const adminContext = await browser.newContext({ viewport: { width, height: 900 } });
    const admin = await adminContext.newPage();
    await signInAsSuperAdmin(admin);
    problems.push(...(await sweep(admin, origin("admin"), platform, width, "platform")));
    await adminContext.close();

    const r = await shopPage(browser, width);
    problems.push(...(await sweep(r.page, origin("sharma"), shop, width, "shop")));
    await r.context.close();

    expect(problems, problems.join("\n")).toEqual([]);
  });
}
