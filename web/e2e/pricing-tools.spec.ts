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
 * Phase 2 review additions (ADR-037/038): per-shop discount grid with server-priced preview,
 * inline special prices, copy pricing between shops, what the shop then sees (360 px), bulk %
 * price-list change and the shop pricing report. Needs the full stack (E2E_FULL_STACK=1).
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
  await page.getByRole("button", { name: `Import ${rows} rows` }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: `Import ${rows} rows` })
    .click();
  await expect(page.getByText(`${rows} rows imported.`)).toBeVisible({ timeout: 120_000 });
}

async function openShop(page: Page, d: NewDistributor, name: string) {
  await page.goto(`${origin(d.slug)}/manage/retailers`);
  await page.getByRole("searchbox", { name: /search retailers/i }).fill(name);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

test.describe("per-shop pricing tools", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop step sets 360 px itself");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`pt${stamp}`);
  const prefix = `T${stamp.slice(-5).toUpperCase()}`;
  const product = (n: number) => `${prefix} Product ${String(n).padStart(4, "0")}`;

  test("a distributor with a price list, 20 products and 4 shops", async ({ page }) => {
    await createDistributor(page, distributor);
    await acceptOwnerInvitation(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/pricing/price-lists`);
    await page.getByRole("button", { name: /add price list/i }).click();
    await page.getByRole("dialog").getByLabel(/^name/i).fill("Gold");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /add price list/i })
      .click();
    await expect(page.getByRole("link", { name: "Gold" })).toBeVisible();
    await importFile(
      page,
      distributor,
      "PRODUCTS",
      workbook(["products", "--count", "20", "--prefix", prefix]),
      "20",
    );
    await importFile(
      page,
      distributor,
      "RETAILERS",
      workbook(["retailers", "--count", "4", "--price-list", "Gold"]),
      "4",
    );
  });

  test("the discount grid previews net prices from the server, then saves", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await openShop(page, distributor, "E2E Shop 001");
    await page.getByRole("link", { name: /discounts by product/i }).click();
    await page.getByRole("searchbox", { name: /search products/i }).fill(`${prefix}-0001`);
    const input = page.getByRole("textbox", { name: `Discount for ${product(1)}` });
    await input.fill("10");
    const row = page.getByRole("row").filter({ hasText: product(1) });
    await expect(row.getByText("₹10.35")).toBeVisible(); // 11.50 - 10%, worked out by the server
    await page.getByRole("button", { name: "Save 1 change" }).click();
    await expect(page.getByText("1 discount saved.")).toBeVisible();
  });

  test("a special price is edited in place on the shop's page", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await openShop(page, distributor, "E2E Shop 001");
    const special = page.getByRole("textbox", { name: `Special price of ${product(2)}` });
    await special.fill("9");
    await special.locator("xpath=ancestor::form").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Special price saved.")).toBeVisible();
  });

  test("pricing is copied to another shop after a preview", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await openShop(page, distributor, "E2E Shop 002");
    await page.getByRole("button", { name: /copy pricing from another shop/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: /copy from/i }).fill("E2E Shop 001");
    await dialog.getByRole("option", { name: /E2E Shop 001/ }).click();
    await dialog.getByRole("radio", { name: /^replace/i }).check();
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText("Price list: standard prices → Gold")).toBeVisible();
    await dialog.getByRole("button", { name: /^copy \d+ changes$/i }).click();
    await expect(page.getByText("Pricing copied.")).toBeVisible();
  });

  test("the second shop now sees the copied discount and special price", async ({ browser }) => {
    const phone = "9811100002";
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

    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(product(1))}`);
    const discounted = page.getByRole("link", { name: new RegExp(product(1)) }).first();
    await expect(discounted.getByText("₹10.35", { exact: true })).toBeVisible();
    await expect(discounted.getByText(/You save ₹1\.15 each \(10%\)/)).toBeVisible();
    await page.goto(`${origin(distributor.slug)}/shop/search?q=${encodeURIComponent(product(2))}`);
    const special = page.getByRole("link", { name: new RegExp(product(2)) }).first();
    await expect(special.getByText("₹9.00", { exact: true })).toBeVisible();
    await context.close();
  });

  test("a price list changes by 5% for one brand, after a preview", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/pricing/price-lists`);
    await page.getByRole("link", { name: "Gold" }).click();
    await page.getByRole("button", { name: /change prices by %/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/change \(%\)/i).fill("5");
    await dialog.getByRole("combobox", { name: /^brand/i }).click();
    await page.getByRole("option", { name: "Acme" }).click();
    await dialog.getByRole("checkbox").check();
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText(/5 prices will change \(5 new on the list\)\./)).toBeVisible();
    await dialog.getByRole("button", { name: "Update 5 prices" }).click();
    await expect(page.getByText("5 prices updated.")).toBeVisible();
  });

  test("the shop pricing report lists both shops", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/pricing/report`);
    await expect(page.getByRole("link", { name: /E2E Shop 001/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /E2E Shop 002/ })).toBeVisible();
  });
});
