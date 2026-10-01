import { expect, test, type Browser } from "@playwright/test";

import { FULL_STACK, OTP_CODE, origin, resetLimits } from "./support/stack";

/**
 * Phase 9b acceptance (spec 5.15, ADR-056) on the seeded demo businesses:
 * - shop activity: the dashboard's "Shops to win back" opens the list; a visit logged for a shop
 *   shows on the list and on the shop's page;
 * - free goods (on for Sharma): a new offer; the shop sees it on the product, gets the free line
 *   in the cart and on the order; staff see it on the order; the offer is deleted again;
 * - flags off (Patel): no free goods, even by typing the address.
 * Figures and refusals are the server's (backend tests prove them). Needs the full stack
 * (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.skip(({ isMobile }) => isMobile, "desktop flows; the responsive sweep covers phones");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SHARMA = origin("sharma");
const PATEL = origin("patel");
const SHOP_PHONE = "9876500001"; // Ganesh Kirana at Sharma Distributors
const PRODUCT_CODE = "SH-0170"; // sold one at a time, in stock, no other offer

async function staff(browser: Browser, slug: string, role: string) {
  const email = `${role}@${slug}.example.com`;
  resetLimits({ emails: [email] });
  const context = await browser.newContext();
  const page = await context.newPage();
  const site = origin(slug);
  await page.goto(`${site}/login`);
  await page.getByLabel(/email address/i).fill(email);
  await page.getByLabel(/^password/i).fill("staff-dev-password");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${site}/manage`);
  return { context, page };
}

async function shop(browser: Browser) {
  resetLimits({ phones: [SHOP_PHONE] });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${SHARMA}/shop/login`);
  await page.getByLabel(/mobile number/i).fill(SHOP_PHONE);
  await page.getByRole("button", { name: /send code/i }).click();
  await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${SHARMA}/shop`);
  return { context, page };
}

test("shops to win back: from the dashboard, and a visit logged for a shop", async ({
  browser,
}) => {
  const { context, page } = await staff(browser, "sharma", "owner");
  const note = `E2E visit ${Date.now().toString(36)}`;
  await page.getByRole("link", { name: /^Shops to win back: \d+/ }).click();
  await expect(page).toHaveURL(`${SHARMA}/manage/retailers/activity`);
  await expect(page.getByRole("heading", { name: "Shop activity" })).toBeVisible();

  await page.getByRole("combobox", { name: "Show" }).click();
  await page.getByRole("option", { name: "All shops" }).click();
  await page.getByRole("searchbox", { name: "Search shops" }).fill("Ganesh Kirana");
  // Wait for the searched list (the heading row and Ganesh Kirana's).
  await expect(page.getByRole("row")).toHaveCount(2);
  const row = page.getByRole("row", { name: /Ganesh Kirana/ });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Log a contact" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "How" }).click();
  await page.getByRole("option", { name: "Visit" }).click();
  await dialog.getByRole("combobox", { name: "What happened" }).click();
  await page.getByRole("option", { name: "Will order" }).click();
  await dialog.getByRole("textbox", { name: "Note" }).fill(note);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Ganesh Kirana leaves the win-back list/)).toBeVisible();
  await expect(row.getByText("Will order")).toBeVisible();

  await row.getByRole("link", { name: /^Ganesh Kirana/ }).click();
  await expect(page.getByText("Ordering", { exact: true })).toBeVisible();
  await expect(page.getByText(note)).toBeVisible();
  await expect(page.getByText("Visit · Will order").first()).toBeVisible();
  await context.close();
});

test("a free-goods offer reaches the shop's cart and order", async ({ browser }) => {
  const owner = await staff(browser, "sharma", "owner");
  const name = `E2E offer ${Date.now().toString(36)}`;
  const page = owner.page;
  await page.goto(`${SHARMA}/manage/pricing/free-goods`);
  await expect(page.getByRole("heading", { name: "Free goods" })).toBeVisible();
  await page.getByRole("link", { name: "Add an offer" }).click();
  await page.getByRole("textbox", { name: /^Name/ }).fill(name);
  await page.getByRole("combobox", { name: /Product bought/ }).fill(PRODUCT_CODE);
  const option = page.getByRole("option", { name: new RegExp(PRODUCT_CODE) });
  const label = (await option.textContent()) ?? "";
  const productName = label.replace(` (${PRODUCT_CODE})`, "").trim();
  await option.click();
  await page.getByRole("textbox", { name: /Quantity to buy/ }).fill("4");
  await page.getByRole("button", { name: "Add the offer" }).click();
  await expect(page).toHaveURL(`${SHARMA}/manage/pricing/free-goods`);
  await expect(page.getByRole("row", { name: new RegExp(name) })).toContainText(
    "Buy 4, get 1 free",
  );

  const retailer = await shop(browser);
  const shopPage = retailer.page;
  await shopPage.goto(`${SHARMA}/shop/search?q=${encodeURIComponent(productName)}`);
  const card = shopPage.getByRole("listitem").filter({ hasText: productName }).first();
  await expect(card.getByText("Buy 4, get 1 free")).toBeVisible();
  const saved = (quantity: string) =>
    shopPage.waitForResponse(
      (r) =>
        r.url().includes("/api/v1/shop/cart/lines/") &&
        r.request().method() === "PUT" &&
        (r.request().postData() ?? "").includes(`"${quantity}"`),
    );
  const added = saved("1");
  await card.getByRole("button", { name: `Add ${productName} to cart` }).click();
  await added;
  const eight = saved("8");
  const qty = card.getByRole("textbox", { name: `Quantity of ${productName}` });
  await qty.fill("8");
  await qty.press("Tab");
  await eight;
  await shopPage.goto(`${SHARMA}/shop/cart`);
  await expect(shopPage.getByText(`with ${name}`)).toBeVisible();
  await expect(shopPage.getByText("2 free")).toBeVisible();
  await expect(shopPage.getByText("Add 4 more to get 1 free")).toBeVisible();
  await shopPage.getByRole("button", { name: /^Place order · ₹/ }).click();
  await expect(shopPage.getByText("Your distributor has it.", { exact: false })).toBeVisible();
  await expect(shopPage.getByText(`with ${name}`)).toBeVisible();
  const orderId = new URL(shopPage.url()).pathname.split("/").pop();
  await retailer.context.close();

  // Staff see the free line on the same order; then the offer goes.
  await page.goto(`${SHARMA}/manage/orders/${orderId}`);
  await expect(page.getByText(`with ${name}`)).toBeVisible();
  await page.goto(`${SHARMA}/manage/pricing/free-goods`);
  await page.getByRole("link", { name }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(`${SHARMA}/manage/pricing/free-goods`);
  await expect(page.getByRole("link", { name })).toHaveCount(0);
  await owner.context.close();
});

test("flags off (Patel): no free goods anywhere", async ({ browser }) => {
  const { context, page } = await staff(browser, "patel", "owner");
  await page.goto(`${PATEL}/manage/pricing/price-lists`);
  await expect(page.getByRole("link", { name: "Discounts" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Free goods" })).toHaveCount(0);
  await page.goto(`${PATEL}/manage/pricing/free-goods`);
  await expect(page.getByText("Free goods are switched off")).toBeVisible();
  await context.close();
});
