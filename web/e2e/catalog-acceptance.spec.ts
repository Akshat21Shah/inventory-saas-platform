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
 * Phase 2 acceptance (spec §12): a distributor imports 1,000 products and 100 retailers from
 * Excel; a retailer signs in and sees only that distributor's products, at correctly resolved
 * prices (its price list where it has one, the standard price otherwise). The shop part runs at
 * 360 px. Needs the full stack and `make seed` (E2E_FULL_STACK=1).
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
  const commit = page.getByRole("button", { name: `Import ${rows} rows` });
  await expect(commit).toBeEnabled({ timeout: 120_000 });
  await commit.click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: `Import ${rows} rows` })
    .click();
  await expect(page.getByText(`${rows} rows imported.`)).toBeVisible({ timeout: 240_000 });
}

test.describe("catalog, retailers and prices", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop step sets 360 px itself");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`p2${stamp}`);
  const prefix = `P${stamp.slice(-5).toUpperCase()}`;
  const onList = "9811100001"; // odd rows of the retailer file are on the price list
  const standard = "9811100002";

  test("the distributor is created and the owner signs in", async ({ page }) => {
    await createDistributor(page, distributor);
    await acceptOwnerInvitation(page, distributor);
  });

  test("1,000 products are imported from Excel", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await importFile(
      page,
      distributor,
      "PRODUCTS",
      workbook(["products", "--count", "1000", "--prefix", prefix]),
      "1,000",
    );
    await page.goto(`${origin(distributor.slug)}/manage/products`);
    await page.getByRole("searchbox", { name: /search products/i }).fill(`${prefix}-0001`);
    await expect(
      page.getByRole("link", { name: new RegExp(`${prefix} Product 0001`) }),
    ).toBeVisible();
  });

  test("a price list gets one special price", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/pricing/price-lists`);
    await page.getByRole("button", { name: /add price list/i }).click();
    const create = page.getByRole("dialog");
    await create.getByLabel(/^name/i).fill("E2E Gold");
    await create.getByRole("button", { name: /add price list/i }).click();
    await page.getByRole("link", { name: "E2E Gold" }).click();
    await page.getByRole("button", { name: /add a product/i }).click();
    const add = page.getByRole("dialog");
    await add.getByRole("combobox", { name: /product/i }).fill(`${prefix}-0001`);
    await add.getByRole("option", { name: new RegExp(`${prefix}-0001`) }).click();
    await add.getByLabel(/list price/i).fill("5");
    await add.getByRole("button", { name: /^save$/i }).click();
    await expect(
      page.getByRole("textbox", { name: new RegExp(`${prefix} Product 0001`) }),
    ).toHaveValue("5.00");
  });

  test("100 retailers are imported from Excel, half of them on the price list", async ({
    page,
  }) => {
    await signInAsOwner(page, distributor);
    await importFile(
      page,
      distributor,
      "RETAILERS",
      workbook(["retailers", "--count", "100", "--price-list", "E2E Gold"]),
      "100",
    );
  });

  test("a shop sees only this distributor's products, at its own prices", async ({ browser }) => {
    resetLimits({ phones: [onList, standard] });
    const context = await browser.newContext({
      viewport: { width: 360, height: 780 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    for (const [phone, expected] of [
      [onList, "₹5.00"], // price list
      [standard, "₹11.50"], // standard price from the file
    ] as const) {
      await page.goto(`${origin(distributor.slug)}/shop/login`);
      await page.getByLabel(/mobile number/i).fill(phone);
      await page.getByRole("button", { name: /send code/i }).click();
      await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
      await page.getByRole("button", { name: /^sign in$/i }).click();
      await page.waitForURL(`${origin(distributor.slug)}/shop`);

      await page.goto(`${origin(distributor.slug)}/shop/search?q=${prefix}%20Product%200001`);
      const card = page.getByRole("link", { name: new RegExp(`${prefix} Product 0001`) }).first();
      await expect(card).toBeVisible();
      await expect(card.getByText(expected, { exact: true })).toBeVisible();

      // Another distributor's products (the seeded demo catalog) never show up.
      await page.goto(`${origin(distributor.slug)}/shop/search?q=Parle`);
      await expect(page.getByText(/nothing found/i)).toBeVisible();
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width).toBeLessThanOrEqual(360); // no sideways scrolling on a small phone

      await page.goto(`${origin(distributor.slug)}/shop/account`);
      await page.getByRole("button", { name: /sign out/i }).click();
      await page.waitForURL(`${origin(distributor.slug)}/shop/login`); // no ?next= after signing out
    }
    await context.close();
  });
});
