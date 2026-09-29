import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  acceptOwnerInvitation,
  createDistributor,
  importFile,
  newDistributor,
  receive,
  signInAsOwner,
  type NewDistributor,
} from "./support/flows";
import { FULL_STACK, OTP_CODE, origin, resetLimits, workbook } from "./support/stack";

/**
 * Phase 6 acceptance (ADR-048), against the running stack with the mock providers:
 * - the super admin turns WhatsApp on for a new distributor; the shop agrees to WhatsApp when
 *   asked after sign-in, and switches the "order accepted" WhatsApp off in Account → Messages
 *   (the bill stays locked on);
 * - the shop orders; the office's bell and inbox show the new order; accepting it rings the
 *   shop's bell, and its message opens the order;
 * - the delivery log shows the in-app message sent and the WhatsApp one not sent, because the
 *   shop switched it off;
 * - the office changes who gets a message and puts it back; posts an announcement the shop sees
 *   on its home; pauses and resumes a shop's payment reminders and sees its WhatsApp consent.
 * Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const PHONE = "9811100001"; // the shop in the retailers workbook
const SHOP = "E2E Shop 001";

async function shopPhone(browser: Browser, d: NewDistributor) {
  resetLimits({ phones: [PHONE] });
  const context = await browser.newContext({
    viewport: { width: 360, height: 780 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  await page.goto(`${origin(d.slug)}/shop/login`);
  await page.getByLabel(/mobile number/i).fill(PHONE);
  await page.getByRole("button", { name: /send code/i }).click();
  await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${origin(d.slug)}/shop`);
  return { context, page };
}

async function openOrder(page: Page, d: NewDistributor, number: string) {
  await page.goto(`${origin(d.slug)}/manage/orders`);
  await page.getByRole("tab", { name: /^New/ }).click();
  await page.getByRole("searchbox", { name: /search orders/i }).fill(number);
  await page.getByRole("link", { name: number }).first().click();
  await expect(page.getByRole("heading", { name: number })).toBeVisible();
}

test.describe("notifications", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop steps set 360 px themselves");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`nt${stamp}`);
  const prefix = `N${stamp.slice(-5).toUpperCase()}`;
  const product = `${prefix} Product 0001`;
  let order = "";

  test("a distributor with WhatsApp on, a product in stock and a shop", async ({ page }) => {
    await createDistributor(page, distributor);
    await page.getByRole("tab", { name: "Modules" }).click();
    const whatsapp = page.getByRole("switch", { name: "WhatsApp messages" });
    await whatsapp.click();
    await expect(whatsapp).toBeChecked();
    await acceptOwnerInvitation(page, distributor);
    await importFile(
      page,
      distributor,
      "PRODUCTS",
      workbook(["products", "--count", "1", "--prefix", prefix]),
      "1",
    );
    await importFile(page, distributor, "RETAILERS", workbook(["retailers", "--count", "1"]), "1");
    await receive(page, distributor, `${prefix}-0001`, product, "20");
  });

  test("the shop agrees to WhatsApp, chooses its messages and orders", async ({ browser }) => {
    const { context, page } = await shopPhone(browser, distributor);
    const question = page.getByRole("dialog", { name: "Get updates on WhatsApp?" });
    await expect(question).toBeVisible();
    await question.getByRole("button", { name: "Yes, send on WhatsApp" }).click();
    await expect(question).toBeHidden();

    await page.goto(`${origin(distributor.slug)}/shop/account/messages`);
    await expect(page.getByRole("switch", { name: "Send me WhatsApp messages" })).toBeChecked();
    await expect(page.getByRole("switch", { name: "New bill: WhatsApp" })).toBeDisabled();
    const accepted = page.getByRole("switch", { name: "Order accepted: WhatsApp" });
    await accepted.click();
    await expect(accepted).not.toBeChecked();

    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(product)}`);
    await page.getByRole("button", { name: `Add ${product} to cart` }).click();
    await page.getByRole("link", { name: /Cart/ }).click();
    await page.getByRole("button", { name: /^Place order · ₹/ }).click();
    await expect(page.getByText("Your distributor has it.", { exact: false })).toBeVisible();
    order = (await page.getByRole("heading", { name: /^ORD-/ }).textContent())!.trim();
    await context.close();
  });

  test("the office hears of the order; accepting it rings the shop's bell", async ({
    page,
    browser,
  }) => {
    await signInAsOwner(page, distributor);
    await page
      .getByRole("link", { name: /^Notifications: \d+ unread$/ })
      .first()
      .click();
    await page.getByRole("button", { name: new RegExp(`New order ${order}`) }).click();
    await expect(page.getByRole("heading", { name: order })).toBeVisible();
    await openOrder(page, distributor, order);
    await page.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByText("To pack")).toBeVisible();

    const { context, page: shop } = await shopPhone(browser, distributor);
    const bell = shop.getByRole("link", { name: /^Notifications: \d+ unread$/ });
    await expect(bell).toBeVisible({ timeout: 30_000 });
    await bell.click();
    await shop.getByRole("button", { name: new RegExp(`Order ${order} accepted`) }).click();
    await expect(shop).toHaveURL(/\/shop\/orders\/[0-9a-f-]+$/);
    await context.close();
  });

  test("the delivery log shows what went out and what the shop switched off", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/settings/notifications/deliveries`);
    await page.getByRole("searchbox", { name: "Search" }).fill(`${order} accepted`);
    const table = page.getByRole("table");
    await expect(table.getByText("Switched off by the person")).toBeVisible({ timeout: 30_000 });
    await expect(table.getByText("In the app").first()).toBeVisible(); // sent in-app
  });

  test("the office changes who gets a message and puts it back", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/settings/notifications`);
    await expect(page.getByText("1 of 1 shops agreed to WhatsApp")).toBeVisible();
    await page.getByRole("button", { name: "Change: Order accepted" }).click();
    const editor = page.getByRole("dialog");
    await editor.getByRole("checkbox", { name: "WhatsApp" }).click();
    await editor.getByRole("button", { name: "Save" }).click();
    await expect(editor).toBeHidden();
    await expect(page.getByText("Changed")).toBeVisible();
    await page.getByRole("button", { name: "Change: Order accepted" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Back to defaults" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: /confirm|yes|continue/i })
      .click();
    await expect(page.getByText("Changed")).toHaveCount(0);
  });

  test("an announcement reaches the shop's home", async ({ page, browser }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/settings/notifications/announcements`);
    await page.getByRole("button", { name: "New announcement" }).click();
    await page.getByLabel("Title").fill("Diwali delivery timings");
    await page.getByLabel("Message").fill("Orders after 2 PM go the next working day.");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Diwali delivery timings").first()).toBeVisible();

    const { context, page: shop } = await shopPhone(browser, distributor);
    await expect(
      shop
        .getByRole("region", { name: "From your distributor" })
        .getByText("Diwali delivery timings"),
    ).toBeVisible();
    await context.close();
  });

  test("a shop's reminders are paused and resumed; its WhatsApp consent shows", async ({
    page,
  }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/retailers`);
    await page.getByRole("link", { name: SHOP }).first().click();
    await expect(page.getByText(/Agreed on .* \(in the app\)/)).toBeVisible();
    await page.getByRole("button", { name: "Pause reminders" }).click();
    await page.getByRole("dialog").getByLabel(/Why/).fill("Disputed bill");
    await page.getByRole("dialog").getByRole("button", { name: "Pause reminders" }).click();
    await expect(page.getByText("Paused: Disputed bill")).toBeVisible();
    await page.getByRole("button", { name: "Resume reminders" }).click();
    await expect(page.getByText("Reminders are going out.")).toBeVisible();
  });
});
