import { expect, test, type Browser } from "@playwright/test";

import { FULL_STACK, OTP_CODE, manage, origin, resetLimits } from "./support/stack";

/**
 * Phase 9c acceptance (ADR-057) on the seeded demo business (Sharma Distributors, the shop
 * Ganesh Kirana):
 * - the shop marks a shipment on its way as received;
 * - with delivery codes, the shop sees its code and staff deliver with it (a wrong code refused);
 * - the shop asks to return an item from a bill; staff approve it into a credit note; the shop
 *   sees the credit note.
 * Shipments come from the dev-only `e2e_dispatch` command. Rules and refusals are the server's
 * (backend tests prove them). Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.skip(({ isMobile }) => isMobile, "desktop flows; the responsive sweep covers phones");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SHARMA = origin("sharma");
const SHOP_PHONE = "9876500001";

interface Sent {
  order: string;
  number: string;
  shipment: string;
  code: string;
}

function dispatch(withCode: boolean): Sent {
  const out = manage(["e2e_dispatch", ...(withCode ? ["--with-code"] : [])]);
  return JSON.parse(out.trim().split("\n").pop()!) as Sent;
}

async function owner(browser: Browser) {
  const email = "owner@sharma.example.com";
  resetLimits({ emails: [email] });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${SHARMA}/login`);
  await page.getByLabel(/email address/i).fill(email);
  await page.getByLabel(/^password/i).fill("staff-dev-password");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${SHARMA}/manage`);
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

test("the shop marks a shipment received", async ({ browser }) => {
  const sent = dispatch(false);
  const { context, page } = await shop(browser);
  await page.goto(`${SHARMA}/shop/orders/${sent.order}`);
  await page.getByRole("button", { name: "I received it" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "I received it" }).click();
  await expect(page.getByRole("button", { name: "I received it" })).toHaveCount(0);
  await expect(page.getByText("Delivered").first()).toBeVisible();
  await context.close();
});

test("with delivery codes, staff deliver with the shop's code", async ({ browser }) => {
  const sent = dispatch(true);
  expect(sent.code).toMatch(/^\d{4}$/);
  const retailer = await shop(browser);
  await retailer.page.goto(`${SHARMA}/shop/orders/${sent.order}`);
  await expect(retailer.page.getByText(sent.code, { exact: true })).toBeVisible();
  await retailer.context.close();

  const { context, page } = await owner(browser);
  await page.goto(`${SHARMA}/manage/orders/${sent.order}`);
  await expect(
    page.getByText("Needs the shop's delivery code to mark it delivered."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Mark delivered" }).click();
  const dialog = page.getByRole("dialog");
  const code = dialog.getByLabel("Shop's delivery code");
  await code.fill(sent.code === "0000" ? "1111" : "0000");
  await dialog.getByRole("button", { name: "Mark delivered" }).click();
  await expect(dialog.getByText(/That isn't the shop's delivery code/)).toBeVisible();
  await code.fill(sent.code);
  await dialog.getByRole("button", { name: "Mark delivered" }).click();
  await expect(page.getByText("Delivered with the shop's code")).toBeVisible();
  await context.close();
});

test("a shop asks to return an item; staff approve it into a credit note", async ({ browser }) => {
  const ids = JSON.parse(manage(["e2e_ids"]).trim().split("\n").pop()!) as {
    returnable_shop_invoice: string;
  };
  const retailer = await shop(browser);
  const shopPage = retailer.page;
  await shopPage.goto(`${SHARMA}/shop/invoices/${ids.returnable_shop_invoice}`);
  await shopPage.getByRole("button", { name: "Return items" }).click();
  const dialog = shopPage.getByRole("dialog");
  await dialog.getByRole("textbox").first().fill("1");
  await dialog.getByRole("button", { name: "Send" }).click();
  await expect(shopPage.getByText("Sent. Your distributor will check it.")).toBeVisible();
  const returns = shopPage.getByRole("region", { name: "Returns" });
  const newest = returns.getByRole("listitem").first();
  await expect(newest.getByText("Waiting for your distributor")).toBeVisible();
  const number = ((await newest.getByText(/^RR-/).textContent()) ?? "").trim();
  expect(number).toMatch(/^RR-\d{4}-\d{6}$/);

  const { context, page } = await owner(browser);
  await page.goto(`${SHARMA}/manage/invoices/returns`);
  await page.getByRole("searchbox", { name: "Search return requests" }).fill(number);
  await page.getByRole("link", { name: number }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved. The credit note is issued.")).toBeVisible();
  await expect(page.getByRole("link", { name: /^CN\// })).toBeVisible();
  await context.close();

  await shopPage.reload();
  const decided = shopPage
    .getByRole("region", { name: "Returns" })
    .getByRole("listitem")
    .filter({ hasText: number });
  await expect(decided.getByText(/Credit note CN\/.+ issued/)).toBeVisible();
  await retailer.context.close();
});
