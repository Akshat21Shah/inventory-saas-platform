import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  acceptOwnerInvitation,
  createDistributor,
  importFile,
  newDistributor,
  receive,
  signInAsOwner,
  signInAsSuperAdmin,
  type NewDistributor,
} from "./support/flows";
import { FULL_STACK, OTP_CODE, origin, randomGstin, resetLimits, workbook } from "./support/stack";

/**
 * Phase 7 acceptance (spec §12, ADR-049), with the mock GST provider and the test gateway:
 * - with the modules off nothing of Phase 7 shows;
 * - the super admin switches e-invoices, e-way bills and online payments on; the owner connects
 *   the GST provider and the test gateway; the shop gets a GSTIN;
 * - dispatch issues the invoice and the worker gets its IRN; an e-way bill without a distance
 *   fails, stays at the top of the dashboard, and is fixed with "Try again";
 * - the shop pays the bill online from its phone: the test gateway sends the signed webhook and
 *   the checkout shows the receipt;
 * - the IRN can't be cancelled while the e-way bill is live; the e-way bill is cancelled, then
 *   the IRN, and the bill re-issued with a new number (still paid).
 * Needs the full stack (E2E_FULL_STACK=1): the worker talks to the mocks.
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const PHONE = "9811100001"; // the shop in the retailers workbook
const SHOP = "E2E Shop 001";
const VEHICLE = "MH12AB1234";
const WORKER = { timeout: 60_000 }; // the worker answers through the mocks

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

async function openInvoice(page: Page, d: NewDistributor, number: string) {
  await page.goto(`${origin(d.slug)}/manage/invoices`);
  await page.getByRole("link", { name: number }).first().click();
  await expect(page.getByRole("heading", { name: `Invoice ${number}` })).toBeVisible();
}

test.describe("e-invoices, e-way bills and online payments", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow; the shop steps set 360 px themselves");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(`gs${stamp}`);
  const prefix = `G${stamp.slice(-5).toUpperCase()}`;
  const product = `${prefix} Product 0001`;
  let invoice = "";

  test("a distributor with a product in stock and a shop", async ({ page }) => {
    await createDistributor(page, distributor);
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

  test("with the modules off, nothing of Phase 7 shows", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await expect(page.getByRole("heading", { name: "E-invoices & e-way bills" })).toHaveCount(0);
    await page.goto(`${origin(distributor.slug)}/manage/settings/business`);
    const settings = page.getByRole("navigation", { name: "Settings sections" });
    await expect(settings.getByRole("link", { name: "Business" })).toBeVisible();
    await expect(settings.getByRole("link", { name: "E-invoices & e-way bills" })).toHaveCount(0);
    await expect(settings.getByRole("link", { name: "Online payments" })).toHaveCount(0);
    await page.goto(`${origin(distributor.slug)}/manage/invoices`);
    await expect(page.getByRole("link", { name: "Credit notes" })).toBeVisible();
    await expect(page.getByRole("link", { name: "E-invoices" })).toHaveCount(0);
    await page.goto(`${origin(distributor.slug)}/manage/settings/compliance`);
    await expect(page.getByText("E-invoices and e-way bills aren't switched on")).toBeVisible();
  });

  test("the super admin switches the modules on; the owner connects the provider and gateway", async ({
    page,
  }) => {
    await signInAsSuperAdmin(page);
    await page.goto(`${origin("admin")}/platform/tenants`);
    await page.getByRole("searchbox").first().fill(distributor.name);
    await page.getByRole("link", { name: distributor.name }).first().click();
    await page.getByRole("tab", { name: "Modules" }).click();
    for (const name of ["E-invoicing", "E-way bills", "Online payments"]) {
      const toggle = page.getByRole("switch", { name });
      await toggle.click();
      await expect(toggle).toBeChecked();
    }

    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/settings/compliance`);
    await page.getByLabel(/^Username/).fill("e2e_api");
    await page.getByLabel(/^Password/).fill("e2e-provider-secret");
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect(page.getByText("Working", { exact: true })).toBeVisible(WORKER);

    await page.goto(`${origin(distributor.slug)}/manage/settings/online-payments`);
    await expect(page.getByRole("combobox", { name: /^Gateway/ })).toHaveText(/Test gateway/);
    await page.getByLabel(/^Key ID/).fill("mock_e2e_key");
    await page.getByLabel(/^Key secret/).fill("e2e-key-secret");
    await page.getByLabel(/^Webhook secret/).fill("e2e-webhook-secret");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Working", { exact: true })).toBeVisible(WORKER);
    await expect(page.getByText(/\/api\/v1\/webhooks\/payments\/mock\//)).toBeVisible();

    // A registered shop (with a GSTIN) gets IRNs.
    await page.goto(`${origin(distributor.slug)}/manage/retailers`);
    await page.getByRole("link", { name: SHOP }).first().click();
    await page.getByLabel(/^GSTIN/).fill(randomGstin());
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Changes saved.")).toBeVisible();
  });

  test("dispatch gets the IRN; a failed e-way bill stays on the dashboard until fixed", async ({
    page,
    browser,
  }) => {
    const number = await shopOrders(browser, distributor, product);
    await signInAsOwner(page, distributor);
    await page.goto(`${origin(distributor.slug)}/manage/orders`);
    await page.getByRole("tab", { name: /^New/ }).click();
    await page.getByRole("searchbox", { name: /search orders/i }).fill(number);
    await page.getByRole("link", { name: number }).first().click();
    await expect(page.getByRole("heading", { name: number })).toBeVisible();
    await page.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByText("To pack")).toBeVisible();
    await page.getByRole("button", { name: "Pack" }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Pack" }).click();
    await page.getByRole("button", { name: "Dispatch" }).first().click();
    await page.getByRole("dialog").getByLabel("Vehicle number").fill(VEHICLE);
    await page.getByRole("dialog").getByRole("button", { name: "Dispatch" }).click();
    const link = page.getByRole("link", { name: /^INV\/\d{2}-\d{2}\/\d{6}$/ });
    await expect(link).toBeVisible();
    invoice = (await link.textContent())!.trim();
    await link.click();

    const irn = page.getByRole("region", { name: "E-invoice (IRN)" });
    await expect(irn.getByText("IRN generated")).toBeVisible(WORKER);
    await expect(irn.getByText("Ack. no.")).toBeVisible();

    // Below the limit no e-way bill is made at dispatch; staff make one. The shop's address has
    // no distance, so the portal refuses it.
    const ewb = page.getByRole("region", { name: "E-way bill" });
    await ewb.getByRole("button", { name: "Make e-way bill" }).click();
    const make = page.getByRole("dialog");
    await make.getByLabel(/^Vehicle number/).fill(VEHICLE);
    await make.getByRole("button", { name: "Make e-way bill" }).click();
    await expect(ewb.getByText(/Enter the distance/)).toBeVisible(WORKER);

    await page.goto(`${origin(distributor.slug)}/manage`);
    const alert = page.getByRole("alert").filter({ hasText: "e-way bill failed" });
    await expect(alert).toBeVisible();
    await expect(alert.getByText(`Vehicle ${VEHICLE}`)).toBeVisible();
    await expect(alert.getByText(/Enter the distance/)).toBeVisible();
    await alert.getByRole("link", { name: "Fix and try again" }).click();
    await expect(page.getByRole("heading", { name: `Invoice ${invoice}` })).toBeVisible();
    await ewb.getByRole("button", { name: "Try again" }).click();
    const retry = page.getByRole("dialog");
    await retry.getByLabel(/^Distance/).fill("12");
    await retry.getByRole("button", { name: "Try again" }).click();
    await expect(ewb.getByText("Generated", { exact: true })).toBeVisible(WORKER);
    await expect(ewb.getByText("E-way bill no.")).toBeVisible();

    await page.goto(`${origin(distributor.slug)}/manage`);
    await expect(page.getByRole("heading", { name: "E-invoices & e-way bills" })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "e-way bill failed" })).toHaveCount(0);
  });

  test("the shop pays the bill online through the test gateway", async ({ page, browser }) => {
    const shop = await shopPhone(browser, distributor);
    await shop.page.goto(`${origin(distributor.slug)}/shop/invoices`);
    await shop.page.getByRole("link", { name: new RegExp(invoice) }).click();
    await shop.page.getByRole("button", { name: /^Pay ₹/ }).click();
    await shop.page.waitForURL(/\/shop\/payments\/checkout\//);
    await shop.page.getByRole("button", { name: /^Pay ₹.* now$/ }).click();
    await shop.page.waitForURL(/\/api\/v1\/dev\/mock-gateway\//);
    await shop.page.getByRole("button", { name: "Pay", exact: true }).click();
    await expect(shop.page.getByText("Paid. Go back to the app.")).toBeVisible();
    await shop.page.getByRole("link", { name: "Back to the app" }).click();
    await expect(shop.page.getByText(/Thank you\. Receipt RCT\//)).toBeVisible(WORKER);
    const wide = await shop.page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(wide).toBe(false);
    await shop.context.close();

    await signInAsOwner(page, distributor);
    await openInvoice(page, distributor, invoice);
    await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
    await page.goto(`${origin(distributor.slug)}/manage/payments/online`);
    await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /^RCT\// }).first()).toBeVisible();
  });

  test("the e-way bill is cancelled, then the IRN, and the bill re-issued", async ({ page }) => {
    await signInAsOwner(page, distributor);
    await openInvoice(page, distributor, invoice);
    const irn = page.getByRole("region", { name: "E-invoice (IRN)" });
    await expect(irn.getByText(/first, then cancel the IRN/)).toBeVisible();
    await expect(irn.getByRole("button", { name: "Cancel IRN" })).toHaveCount(0);

    const ewb = page.getByRole("region", { name: "E-way bill" });
    await ewb.getByRole("button", { name: "Cancel e-way bill" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel e-way bill" }).click();
    await expect(ewb.getByText("Cancelled", { exact: true })).toBeVisible(WORKER);

    await page.reload();
    await irn.getByRole("button", { name: "Cancel IRN" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("The new invoice will be made out to")).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel IRN" }).click();
    await expect(page.getByText(/This invoice is cancelled/)).toBeVisible(WORKER);
    await page
      .getByRole("link", { name: /^Re-issued as INV\// })
      .first()
      .click();
    await expect(page.getByRole("heading", { name: /^Invoice INV\// })).not.toHaveText(
      `Invoice ${invoice}`,
    );
    await expect(
      page.getByRole("region", { name: "E-invoice (IRN)" }).getByText("IRN generated"),
    ).toBeVisible(WORKER);
    await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible(); // money moved
  });
});
