import { expect, test, type Page } from "@playwright/test";

import {
  acceptOwnerInvitation,
  createDistributor,
  newDistributor,
  signInAsOwner,
  type NewDistributor,
} from "./support/flows";
import { FULL_STACK, OTP_CODE, origin, resetLimits, workbook } from "./support/stack";

/**
 * Phase 3 acceptance (spec §12): goods receipts and adjustments update stock with the right
 * movements, alerts fire once, and shops see stock labels (360 px). The concurrency guarantees are
 * proven by the backend's threaded tests. Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

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

async function openStockOf(page: Page, d: NewDistributor, code: string) {
  await page.goto(`${origin(d.slug)}/manage/stock`);
  await page.getByRole("searchbox", { name: /search stock/i }).fill(code);
  await page.getByRole("link", { name: new RegExp(code) }).click();
  await expect(page.getByRole("heading", { name: "Stock movements", exact: true })).toBeVisible();
}

test.describe("inventory", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop step sets 360 px itself");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`iv${stamp}`);
  const prefix = `S${stamp.slice(-5).toUpperCase()}`;
  const code = (n: number) => `${prefix}-${String(n).padStart(4, "0")}`;

  test("a distributor with 3 products and a shop", async ({ page }) => {
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
  });

  test("the reorder level is set on the product's stock page", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await openStockOf(page, distributor, code(1));
    await page.getByLabel("Reorder at (PCS)").fill("5");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Reorder level saved")).toBeVisible();
  });

  test("goods are received by scanning a code, with a cost, and posted", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/stock/inwards/new`);
    await page.getByLabel("Supplier", { exact: true }).fill("E2E Wholesale");
    const scan = page.getByLabel("Scan or search a product");
    await scan.fill(code(1));
    await scan.press("Enter"); // what a USB scanner does
    const qty = page.getByLabel(`Quantity of ${prefix} Product 0001 in PCS`);
    await expect(qty).toBeFocused();
    await qty.fill("12");
    await qty.press("Enter");
    await page.getByLabel(`Cost per PCS (before GST): ${prefix} Product 0001`).fill("7.5");
    await page.getByRole("button", { name: "Save and post" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Post" }).click();
    await expect(page.getByRole("heading", { name: /^GRN-\d{4}-00001$/ })).toBeVisible();
    await expect(page.getByText("₹90.00")).toHaveCount(2); // line and total: 12 x 7.50, by the server

    await openStockOf(page, distributor, code(1));
    const movements = page.getByRole("region", { name: "Stock movements" });
    await expect(movements.getByRole("link", { name: /^GRN-\d{4}-00001$/ })).toBeVisible();
    await expect(movements.getByText("Goods received")).toBeVisible();
    await expect(page.getByText("₹7.50")).toBeVisible(); // cost price from the receipt
  });

  test("damage lowers the stock and the low-stock alert opens once", async ({ page }) => {
    await signInAsOwner(page, distributor);
    for (const [qty, note] of [
      ["9", "Wet cartons"],
      ["1", "Torn pack"],
    ] as const) {
      await page.goto(`${origin(distributor.slug)}/manage/stock/adjustments/new`);
      await page.getByRole("radio", { name: "Damaged" }).check({ force: true });
      await page.getByLabel(/^note/i).fill(note);
      const scan = page.getByLabel("Scan or search a product");
      await scan.fill(code(1));
      await scan.press("Enter");
      await page.getByRole("radio", { name: "Remove" }).click();
      await page.getByLabel(`Quantity of ${prefix} Product 0001 to remove, in PCS`).fill(qty);
      await page.getByRole("button", { name: /save adjustment/i }).click();
      await expect(page.getByRole("heading", { name: /^ADJ-\d{4}-0000\d$/ })).toBeVisible();
    }
    await openStockOf(page, distributor, code(1));
    await expect(page.getByText("Damaged").first()).toBeVisible();
    await page.goto(`${origin(distributor.slug)}/manage/stock/alerts`);
    // 12 - 9 = 3 (low), then 2 (still low): one open alert, not two.
    await expect(page.getByRole("link", { name: new RegExp(code(1)) })).toHaveCount(1);
    await expect(page.getByRole("table").getByText("Low stock")).toHaveCount(1);
  });

  test("the shop sees stock labels, never quantities, at 360 px", async ({ browser }) => {
    const phone = "9811100001";
    resetLimits({ phones: [phone] });
    const context = await browser.newContext({
      viewport: { width: 360, height: 780 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await page.goto(`${origin(distributor.slug)}/shop/login`);
    await page.getByLabel(/mobile number/i).fill(phone);
    await page.getByRole("button", { name: /send code/i }).click();
    await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL(`${origin(distributor.slug)}/shop`);
    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(prefix)}`);
    const low = page.getByRole("link", { name: new RegExp(`${prefix} Product 0001`) }).first();
    await expect(low.getByText("Low stock")).toBeVisible();
    await expect(low.getByText(/in stock$/)).toHaveCount(0); // exact stock is off by default
    const none = page.getByRole("link", { name: new RegExp(`${prefix} Product 0002`) }).first();
    await expect(none.getByText("Available on backorder")).toBeVisible();
    const wide = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(wide).toBe(false);
    await context.close();
  });
});
