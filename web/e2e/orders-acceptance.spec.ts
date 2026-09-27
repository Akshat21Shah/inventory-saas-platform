import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  acceptOwnerInvitation,
  createDistributor,
  newDistributor,
  signInAsOwner,
  type NewDistributor,
} from "./support/flows";
import { FULL_STACK, OTP_CODE, origin, resetLimits, workbook } from "./support/stack";

/**
 * Phase 4 acceptance (spec §12, ADR-044/045): a shop orders from a phone in 3 taps; a dropped
 * connection during checkout never makes a second order; staff accept, pack, dispatch and
 * deliver while the shop watches the order change live; stock arriving for a backorder is
 * confirmed into a second shipment; staff order for a shop. Race conditions are proven by the
 * backend's threaded tests. Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const PHONE = "9811100001"; // the shop in the retailers workbook

async function importFile(page: Page, d: NewDistributor, kind: string, file: Buffer, rows: string) {
  await page.goto(`${origin(d.slug)}/manage/imports/new?kind=${kind}`);
  await page.getByRole("radio", { name: /^add new only/i }).check();
  await page.getByLabel(/choose an excel or csv file/i).setInputFiles({
    name: `${kind.toLowerCase()}.xlsx`,
    mimeType: XLSX,
    buffer: file,
  });
  await page.getByRole("button", { name: /check the file/i }).click();
  const label = `Import ${rows} ${rows === "1" ? "row" : "rows"}`;
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: label }).click();
  await expect(page.getByText(`${rows} ${rows === "1" ? "row" : "rows"} imported.`)).toBeVisible({
    timeout: 120_000,
  });
}

async function receive(page: Page, d: NewDistributor, code: string, name: string, qty: string) {
  await page.goto(`${origin(d.slug)}/manage/stock/inwards/new`);
  await page.getByLabel("Supplier", { exact: true }).fill("E2E Wholesale");
  const scan = page.getByLabel("Scan or search a product");
  await scan.fill(code);
  await scan.press("Enter");
  const field = page.getByLabel(`Quantity of ${name} in PCS`);
  await field.fill(qty);
  await field.press("Enter");
  await page.getByRole("button", { name: "Save and post" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Post" }).click();
  await expect(page.getByRole("heading", { name: /^GRN-\d{4}-\d{5}$/ })).toBeVisible();
}

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

async function openOrder(page: Page, d: NewDistributor, number: string, tab: string) {
  await page.goto(`${origin(d.slug)}/manage/orders`);
  await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
  await page.getByRole("searchbox", { name: /search orders/i }).fill(number);
  await page.getByRole("link", { name: number }).first().click();
  await expect(page.getByRole("heading", { name: number })).toBeVisible();
}

/** Pack everything, dispatch and deliver the first shipment still to pack. */
async function shipAll(page: Page) {
  await page.getByRole("button", { name: "Pack" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Pack" }).click();
  await page.getByRole("button", { name: "Dispatch" }).first().click();
  await page.getByRole("dialog").getByLabel("Vehicle number").fill("MH12AB1234");
  await page.getByRole("dialog").getByRole("button", { name: "Dispatch" }).click();
  await page.getByRole("button", { name: "Mark delivered" }).first().click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Mark delivered" }).click();
}

test.describe("orders", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop steps set 360 px themselves");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`or${stamp}`);
  const prefix = `O${stamp.slice(-5).toUpperCase()}`;
  const code = (n: number) => `${prefix}-${String(n).padStart(4, "0")}`;
  const name = (n: number) => `${prefix} Product ${String(n).padStart(4, "0")}`;
  const numbers: string[] = [];

  test("a distributor with products, stock for one of them, and a shop", async ({ page }) => {
    await createDistributor(page, distributor);
    await acceptOwnerInvitation(page, distributor);
    await importFile(
      page,
      distributor,
      "PRODUCTS",
      workbook(["products", "--count", "3", "--prefix", prefix]),
      "3",
    );
    await importFile(page, distributor, "RETAILERS", workbook(["retailers", "--count", "1"]), "1");
    await receive(page, distributor, code(1), name(1), "20");
  });

  test("the shop goes from search to a placed order in 3 taps at 360 px", async ({ browser }) => {
    const { context, page } = await shopPhone(browser, distributor);
    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(name(1))}`);
    // Tap 1: Add on the search result. Tap 2: the cart. Tap 3: Place order.
    await page.getByRole("button", { name: `Add ${name(1)} to cart` }).click();
    await expect(page.getByRole("link", { name: /1 item in the cart/ })).toBeVisible();
    await page.getByRole("link", { name: /Cart/ }).click();
    await page.getByRole("button", { name: /^Place order · ₹/ }).click();
    await expect(page.getByText("Your distributor has it.", { exact: false })).toBeVisible();
    const number = (await page.getByRole("heading", { name: /^ORD-/ }).textContent())!.trim();
    numbers.push(number);
    const wide = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(wide).toBe(false);
    await context.close();
  });

  test("a dropped connection while placing never makes a second order", async ({ browser }) => {
    const { context, page } = await shopPhone(browser, distributor);
    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(prefix)}`);
    await page.getByRole("button", { name: `Add ${name(1)} to cart` }).click();
    await page.getByRole("button", { name: `Add ${name(2)} to cart` }).click(); // out of stock
    await page.getByRole("link", { name: /Cart/ }).click();
    await expect(page.getByRole("heading", { name: "Comes later" })).toBeVisible();
    // The server places the order, but the answer never reaches the phone.
    let dropped = false;
    await page.route("**/api/v1/shop/orders/", async (route) => {
      if (route.request().method() === "POST" && !dropped) {
        dropped = true;
        await route.fetch();
        await route.abort("internetdisconnected");
      } else {
        await route.continue();
      }
    });
    await page.getByRole("button", { name: /^Place order · ₹/ }).click();
    await expect(page.getByText(/The connection dropped/)).toBeVisible();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("Your distributor has it.", { exact: false })).toBeVisible();
    const number = (await page.getByRole("heading", { name: /^ORD-/ }).textContent())!.trim();
    numbers.push(number);
    await page.goto(`${origin(distributor.slug)}/shop/orders`);
    await expect(page.getByRole("link", { name: /^ORD-/ })).toHaveCount(2); // not 3
    await context.close();
  });

  test("staff accept and ship while the shop watches live: partly delivered", async ({
    page,
    browser,
  }) => {
    const [, second] = numbers;
    const shop = await shopPhone(browser, distributor);
    await shop.page.goto(`${origin(distributor.slug)}/shop/orders`);
    await shop.page.getByRole("link", { name: new RegExp(second!) }).click();
    await expect(shop.page.getByText("Placed", { exact: true }).first()).toBeVisible();

    await signInAsOwner(page, distributor);
    await openOrder(page, distributor, second!, "New");
    await page.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByText("To pack")).toBeVisible();
    // The shop's screen changes without a reload.
    await expect(shop.page.getByText(`Order ${second} was accepted.`)).toBeVisible();
    await expect(shop.page.getByText("Accepted", { exact: true }).first()).toBeVisible();

    await shipAll(page);
    await expect(page.getByText("1 item to follow").first()).toBeVisible();
    await expect(shop.page.getByText("Partly delivered").first()).toBeVisible();
    await expect(shop.page.getByText("1 item to follow").first()).toBeVisible();
    await shop.context.close();
  });

  test("stock arrives for the backorder, is confirmed and delivered", async ({ page }) => {
    const [, second] = numbers;
    await signInAsOwner(page, distributor);
    await receive(page, distributor, code(2), name(2), "5");
    await page.goto(`${origin(distributor.slug)}/manage/backorders`);
    const proposals = page.getByRole("region", { name: "Stock to confirm" });
    await expect(proposals.getByRole("link", { name: second! })).toBeVisible();
    await proposals.getByRole("button", { name: "Confirm" }).first().click();
    await expect(page.getByText("1 allocation confirmed")).toBeVisible();
    await openOrder(page, distributor, second!, "In progress");
    await expect(page.getByText("backorder").first()).toBeVisible();
    await shipAll(page);
    await expect(page.getByText("Completed").first()).toBeVisible();
  });

  test("staff order for the shop from their own cart", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/orders/new`);
    await page.getByRole("button", { name: /E2E Shop 001/ }).click();
    await page.getByRole("searchbox", { name: "Search products" }).fill(prefix);
    await page.getByRole("button", { name: "Add" }).first().click();
    await expect(page.getByRole("button", { name: /^Place order · ₹/ })).toBeEnabled();
    await page.getByRole("button", { name: /^Place order · ₹/ }).click();
    await expect(page.getByText(/Placed by E2E Owner/)).toBeVisible();
  });
});
