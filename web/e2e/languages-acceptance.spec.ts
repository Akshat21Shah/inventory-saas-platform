import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { inflateSync } from "node:zlib";

import english from "../messages/en.json";
import hindi from "../messages/hi.json";
import marathi from "../messages/mr.json";
import { FULL_STACK, OTP_CODE, manage, origin, resetLimits } from "./support/stack";

/**
 * Phase 11a acceptance (ADR-060): a shop picks Hindi on its sign-in page and orders in Hindi,
 * searching in Devanagari; the owner switches to Marathi and accepts the order in Marathi; the
 * shop hears of it in Hindi, live, and its Order Confirmation PDF carries Hindi labels (the
 * Devanagari font is in it). On the seeded Sharma Distributors, a test distributor for languages.
 * Needs the full stack (E2E_FULL_STACK=1); puts everyone back to English at the end.
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SLUG = "sharma";
const PHONE = "9876500001"; // Ganesh Kirana
const OWNER = "owner@sharma.example.com";
const NOTIFICATIONS = join(__dirname, "..", "..", "backend", "apps", "notifications");

type Catalog = typeof english;
/** A screen text in a language, with its {values} filled in (no plurals needed here). */
function say(catalog: Catalog, path: string, values: Record<string, string> = {}): string {
  let text = path
    .split(".")
    .reduce<unknown>((at, key) => (at as Record<string, unknown>)[key], catalog);
  for (const [name, value] of Object.entries(values)) {
    text = String(text).replaceAll(`{${name}}`, value);
  }
  return String(text);
}

/** The Hindi notification text the platform sends (the catalogue file), filled in. */
function hindiNotice(event: string, values: Record<string, string>): string {
  const texts = JSON.parse(readFileSync(join(NOTIFICATIONS, "catalog_texts", "hi.json"), "utf-8"));
  let text: string = texts[event].SHOP.IN_APP.subject;
  for (const [name, value] of Object.entries(values)) {
    text = text.replaceAll(`{{ ${name} }}`, value);
  }
  return text;
}

/** Whether a PDF embeds a Devanagari font (its streams are compressed: inflate each). */
function hasDevanagariFont(pdf: Buffer): boolean {
  const text = pdf.toString("latin1");
  const pattern = /stream\r?\n([\s\S]*?)\r?\nendstream/g;
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    try {
      if (inflateSync(Buffer.from(match[1]!, "latin1")).includes("Devanagari")) return true;
    } catch {
      // Not a compressed stream.
    }
  }
  return text.includes("Devanagari");
}

function everyoneInEnglish() {
  manage(["e2e_language", "en", "--email", OWNER, "--phone", PHONE]);
}

let orderId = "";
let orderNumber = "";

test.describe("languages", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop sets 360 px itself");
  test.beforeAll(everyoneInEnglish);
  test.afterAll(everyoneInEnglish);

  test("a shop picks Hindi on its sign-in page and orders in Hindi", async ({ browser }) => {
    resetLimits({ phones: [PHONE] });
    const context = await browser.newContext({
      viewport: { width: 360, height: 780 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await page.goto(`${origin(SLUG)}/shop/login`);
    await page.getByRole("combobox", { name: say(english, "auth.language") }).click();
    await page.getByRole("option", { name: "हिन्दी" }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", "hi");
    await page.getByLabel(say(hindi, "auth.retailer.phoneLabel")).fill(PHONE);
    await page.getByRole("button", { name: say(hindi, "auth.retailer.sendCode") }).click();
    await page.getByLabel(say(hindi, "auth.retailer.codeLabel")).fill(OTP_CODE);
    await page.getByRole("button", { name: say(hindi, "auth.retailer.verify") }).click();
    await page.waitForURL(`${origin(SLUG)}/shop`);
    await expect(page.locator("html")).toHaveAttribute("lang", "hi");

    // Searching in Devanagari finds the products named in English ("Basmati Rice").
    await page.goto(`${origin(SLUG)}/shop/search?q=${encodeURIComponent("चावल")}`);
    const add = page.getByRole("button", { name: /कार्ट में जोड़ें$/ }).first();
    await expect(add).toBeVisible();
    await expect(page.getByText(/Rice/).first()).toBeVisible();
    await add.click();
    await page
      .getByRole("link", { name: new RegExp(say(hindi, "nav.cart")) })
      .first()
      .click();
    await page.getByRole("button", { name: /^ऑर्डर दें · ₹/ }).click();
    const heading = page.getByRole("heading", { name: /^ORD-/ });
    await expect(heading).toBeVisible();
    orderNumber = (await heading.textContent())!.trim();
    await page.goto(`${origin(SLUG)}/shop/orders`);
    await page
      .getByRole("link", { name: new RegExp(orderNumber) })
      .first()
      .click();
    await page.waitForURL(/\/shop\/orders\/[0-9a-f-]{36}$/);
    orderId = page.url().split("/").pop()!;
    // Amounts stay in the digits 0-9 with Indian grouping.
    await expect(page.getByText(/₹[0-9,]+\.[0-9]{2}/).first()).toBeVisible();
    await context.close();
  });

  test("the owner switches to Marathi and accepts it; the shop hears in Hindi", async ({
    page,
    browser,
  }) => {
    // The shop watches its order.
    resetLimits({ phones: [PHONE] });
    const shopContext = await browser.newContext({ viewport: { width: 360, height: 780 } });
    const shop = await shopContext.newPage();
    await shop.goto(`${origin(SLUG)}/shop/login`);
    // Hindi now: saved to the shop when it signed in.
    await shop.getByLabel(say(english, "auth.retailer.phoneLabel")).fill(PHONE);
    await shop.getByRole("button", { name: say(english, "auth.retailer.sendCode") }).click();
    await shop.getByLabel(say(english, "auth.retailer.codeLabel")).fill(OTP_CODE);
    await shop.getByRole("button", { name: say(english, "auth.retailer.verify") }).click();
    await shop.waitForURL(`${origin(SLUG)}/shop`);
    await expect(shop.locator("html")).toHaveAttribute("lang", "hi");
    await shop.goto(`${origin(SLUG)}/shop/orders/${orderId}`);

    await signInOwner(page);
    await page.goto(`${origin(SLUG)}/manage/account`);
    await page.getByRole("combobox", { name: say(english, "account.language") }).click();
    await page.getByRole("option", { name: "मराठी" }).click();
    await page
      .getByRole("button", { name: say(english, "account.save") })
      .first()
      .click();
    await expect(page.locator("html")).toHaveAttribute("lang", "mr");

    await page.goto(`${origin(SLUG)}/manage/orders/${orderId}`);
    await expect(page.getByRole("heading", { name: orderNumber })).toBeVisible();
    await page.getByRole("button", { name: say(marathi, "orders.detail.accept") }).click();
    // The shop's screen hears of it at once, in Hindi.
    await expect(
      shop.getByText(hindiNotice("order.accepted", { order_number: orderNumber })).first(),
    ).toBeVisible({ timeout: 30_000 });

    // Its Order Confirmation is printed with Hindi labels.
    const confirmation = shop.getByRole("button", { name: say(hindi, "shop.orders.confirmation") });
    await expect(confirmation).toBeVisible({ timeout: 30_000 });
    let pdf: Buffer | null = null;
    for (let tries = 0; tries < 20 && !pdf; tries++) {
      // The button opens a tab and points it at the file (a short-lived storage link).
      const requested = shop
        .context()
        .waitForEvent("request", {
          predicate: (r) => new URL(r.url()).pathname.endsWith(".pdf"),
          timeout: 10_000,
        })
        .catch(() => null);
      await confirmation.click();
      const request = await requested;
      if (request) pdf = Buffer.from(await (await shop.request.get(request.url())).body());
      for (const tab of shop.context().pages()) if (tab !== shop) await tab.close();
      if (!pdf) await shop.waitForTimeout(1500); // still being prepared
    }
    expect(pdf, "the Order Confirmation PDF").not.toBeNull();
    expect(pdf!.subarray(0, 5).toString()).toBe("%PDF-");
    expect(hasDevanagariFont(pdf!)).toBe(true);
    await shopContext.close();
  });
});

async function signInOwner(page: Page) {
  resetLimits({ emails: [OWNER] });
  await page.goto(`${origin(SLUG)}/login`);
  await page.getByLabel(/email address/i).fill(OWNER);
  await page.getByLabel(/^password/i).fill("staff-dev-password");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${origin(SLUG)}/manage`);
}
