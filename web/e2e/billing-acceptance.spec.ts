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
 * Phase 5 acceptance (spec §12, ADR-046/047), both invoice timings:
 * - at dispatch (the default): the invoice is issued for what was packed and printed by the
 *   worker; the shop pays in full and gets a receipt; goods come back on a credit note, which
 *   becomes credit, and part of it is refunded with a voucher; the shop sees the paid bill, its
 *   statement and the receipt on a phone;
 * - at acceptance: the invoice is issued when the order is accepted, with the Order
 *   Confirmation, and cancelling the order issues a credit note automatically.
 * Amounts are the server's; the ledger's arithmetic is proven by the backend's reconciliation
 * property test. Needs the full stack (E2E_FULL_STACK=1).
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

/** The shop orders one product from its phone; returns the order number. */
async function shopOrders(browser: Browser, d: NewDistributor, product: string) {
  const { context, page } = await shopPhone(browser, d);
  await page.goto(`${origin(d.slug)}/shop/search?q=${encodeURIComponent(product)}`);
  await page.getByRole("button", { name: `Add ${product} to cart` }).click();
  await page.getByRole("link", { name: /Cart/ }).click();
  await page.getByRole("button", { name: /^Place order · ₹/ }).click();
  await expect(page.getByText("Your distributor has it.", { exact: false })).toBeVisible();
  const number = (await page.getByRole("heading", { name: /^ORD-/ }).textContent())!.trim();
  await context.close();
  return number;
}

async function openOrder(page: Page, d: NewDistributor, number: string, tab: string) {
  await page.goto(`${origin(d.slug)}/manage/orders`);
  await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
  await page.getByRole("searchbox", { name: /search orders/i }).fill(number);
  await page.getByRole("link", { name: number }).first().click();
  await expect(page.getByRole("heading", { name: number })).toBeVisible();
}

/** Clicks a document button until the worker has printed the PDF: the server then answers
 * with a signed link to a .pdf file. */
async function expectPdf(page: Page, button: string, path: RegExp) {
  for (let attempt = 0; attempt < 20; attempt++) {
    const response = page.waitForResponse((r) => path.test(new URL(r.url()).pathname));
    const popup = page.waitForEvent("popup").catch(() => null);
    await page.getByRole("button", { name: button }).first().click();
    const body = (await (await response).json()) as { status: string; url: string | null };
    (await popup)?.close().catch(() => undefined);
    if (body.status === "READY") {
      expect(body.url).toMatch(/\.pdf/);
      return;
    }
    expect(body.status).toBe("PENDING");
    await page.waitForTimeout(3_000);
  }
  throw new Error(`${button}: the PDF was never ready`);
}

test.describe("billing", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop steps set 360 px themselves");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`bl${stamp}`);
  const prefix = `B${stamp.slice(-5).toUpperCase()}`;
  const code = (n: number) => `${prefix}-${String(n).padStart(4, "0")}`;
  const name = (n: number) => `${prefix} Product ${String(n).padStart(4, "0")}`;
  let invoice = "";

  test("a distributor with products in stock and a shop", async ({ page }) => {
    await createDistributor(page, distributor);
    await acceptOwnerInvitation(page, distributor);
    await importFile(
      page,
      distributor,
      "PRODUCTS",
      workbook(["products", "--count", "2", "--prefix", prefix]),
      "2",
    );
    await importFile(page, distributor, "RETAILERS", workbook(["retailers", "--count", "1"]), "1");
    await receive(page, distributor, code(1), name(1), "20");
    await receive(page, distributor, code(2), name(2), "20");
  });

  test("at dispatch: the invoice is issued, printed and paid with a receipt", async ({
    page,
    browser,
  }) => {
    const number = await shopOrders(browser, distributor, name(1));
    await signInAsOwner(page, distributor);
    await openOrder(page, distributor, number, "New");
    await page.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByText("To pack")).toBeVisible();
    await expect(page.getByRole("link", { name: /^INV\// })).toHaveCount(0); // not at acceptance
    await page.getByRole("button", { name: "Pack" }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Pack" }).click();
    await page.getByRole("button", { name: "Dispatch" }).first().click();
    await page.getByRole("dialog").getByLabel("Vehicle number").fill("MH12AB1234");
    await page.getByRole("dialog").getByRole("button", { name: "Dispatch" }).click();

    const link = page.getByRole("link", { name: /^INV\/\d{2}-\d{2}\/\d{6}$/ });
    await expect(link).toBeVisible();
    invoice = (await link.textContent())!.trim();
    await link.click();
    await expect(page.getByRole("heading", { name: `Invoice ${invoice}` })).toBeVisible();
    await expect(page.getByText("Unpaid", { exact: true }).first()).toBeVisible();
    await expectPdf(page, "Download PDF", /\/invoices\/[^/]+\/pdf\/$/);
    const total = (await page
      .getByText("Invoice total")
      .locator("..")
      .locator("dd")
      .textContent())!.replace(/[₹,\s]/g, "");

    // Pay it in full from the shop's account page.
    await page.getByRole("link", { name: SHOP }).click();
    await page.getByRole("link", { name: "Statement and payments" }).click();
    await page.getByRole("link", { name: "Record payment" }).click();
    await page.getByLabel(/^Amount/).fill(total);
    await page.getByRole("button", { name: "Record payment" }).click();
    await expect(page.getByRole("heading", { name: /^Receipt RCT\// })).toBeVisible();
    await expect(page.getByRole("link", { name: `Invoice ${invoice}` })).toBeVisible();
    await expectPdf(page, "Download receipt", /\/payments\/[^/]+\/receipt\/$/);
  });

  test("goods come back on a credit note, and part of the credit is refunded", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/invoices`);
    await page.getByRole("link", { name: invoice }).first().click();
    await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
    await page.getByRole("link", { name: "Credit note", exact: true }).click();
    await page.getByLabel("Quantity back").fill("1");
    await page.getByRole("button", { name: "Issue credit note" }).click();
    await expect(page.getByRole("heading", { name: /^Credit note CN\// })).toBeVisible();
    await expect(page.getByText(/Not used yet: kept as credit/)).toBeVisible();
    await expectPdf(page, "Download PDF", /\/credit-notes\/[^/]+\/pdf\/$/);

    await page.goto(`${origin(distributor.slug)}/manage/receivables`);
    await page.getByRole("link", { name: SHOP }).first().click();
    await page.getByRole("link", { name: "Refund credit" }).click();
    await page.getByLabel(/^Amount/).fill("1.00");
    await page.getByRole("button", { name: "Record refund" }).click();
    await expect(page.getByRole("heading", { name: /^Refund RFD\// })).toBeVisible();
    await expectPdf(page, "Download voucher", /\/refunds\/[^/]+\/voucher\/$/);
  });

  test("the shop sees the paid bill, its statement and the receipt on a phone", async ({
    browser,
  }) => {
    const { context, page } = await shopPhone(browser, distributor);
    await page
      .getByRole("link", { name: /Account/ })
      .last()
      .click();
    await expect(page.getByText("Your credit with us")).toBeVisible();
    await page.getByRole("link", { name: "My bills" }).click();
    await page.getByRole("tab", { name: "Paid" }).click();
    await page.getByRole("link", { name: new RegExp(invoice) }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`Bill ${invoice}`) })).toBeVisible();
    await expect(page.getByText(/1 returned/)).toBeVisible();
    await expectPdf(page, "Download bill", /\/shop\/invoices\/[^/]+\/pdf\/$/);
    await page.goto(`${origin(distributor.slug)}/shop/statement`);
    for (const entry of ["Invoice", "Payment", "Credit note", "Refund"]) {
      await expect(page.getByText(new RegExp(`^${entry} `)).first()).toBeVisible();
    }
    await page.goto(`${origin(distributor.slug)}/shop/payments`);
    await expectPdf(page, "Receipt", /\/shop\/payments\/[^/]+\/receipt\/$/);
    const wide = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(wide).toBe(false);
    await context.close();
  });

  test("at acceptance: the invoice and Order Confirmation come at once; cancelling credits it automatically", async ({
    page,
    browser,
  }) => {
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/settings/policies/invoicing`);
    await page.getByLabel("When to create the tax invoice").click();
    await page.getByRole("option", { name: "When the order is accepted" }).click();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Settings saved")).toBeVisible();

    const number = await shopOrders(browser, distributor, name(2));
    await openOrder(page, distributor, number, "New");
    await page.getByRole("button", { name: "Accept" }).click();
    const link = page.getByRole("link", { name: /^INV\/\d{2}-\d{2}\/\d{6}$/ });
    await expect(link).toBeVisible();
    await expectPdf(page, "Order Confirmation", /\/orders\/[^/]+\/confirmation\/$/);

    await page.getByRole("button", { name: "Cancel order" }).click();
    await page
      .getByRole("dialog")
      .getByLabel(/reason/i)
      .fill("Shop closed for the season");
    await page.getByRole("dialog").getByRole("button", { name: "Cancel order" }).click();
    await expect(page.getByText("Cancelled", { exact: true }).first()).toBeVisible();
    await link.click();
    await expect(page.getByText("Issued automatically").first()).toBeVisible();
    await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible(); // fully credited

    await page.goto(`${origin(distributor.slug)}/manage/invoices/credit-notes`);
    await expect(
      page.getByText("Issued automatically (short supply / cancellation)").first(),
    ).toBeVisible();
  });
});
