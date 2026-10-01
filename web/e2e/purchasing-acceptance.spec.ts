import { expect, test, type Browser, type Page } from "@playwright/test";

import { FULL_STACK, linkFromEmail, origin, resetLimits } from "./support/stack";

/**
 * Phase 9a acceptance (spec 5.7, 5.15, 5.17; ADR-053) on the seeded demo businesses:
 * - global search: a shop's mobile number opens the shop on Enter; "See all" opens the products
 *   list with the same search;
 * - purchasing (on for Sharma): a new supplier, a purchase order sent by email with a link to its
 *   PDF, received into a goods receipt past the over-receipt tolerance (confirmed), and the order
 *   received;
 * - stock planning: a reorder suggestion explained in plain words becomes a draft purchase order;
 * - permissions: the salesperson gets no purchasing;
 * - flags off (Patel): no purchasing or stock planning anywhere, even by typing the address.
 * Figures and refusals are the server's (backend tests prove them, incl. the API with the modules
 * off). Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.skip(({ isMobile }) => isMobile, "desktop flows; the responsive sweep covers phones");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SHARMA = origin("sharma");
const PATEL = origin("patel");

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

async function openSearch(page: Page, text: string) {
  await page.keyboard.press("Control+K");
  const input = page.getByRole("combobox", { name: "Search" });
  await input.fill(text);
  return input;
}

/** The purchase order's row on the list, found by its number. */
async function orderRow(page: Page, number: string) {
  await page.goto(`${SHARMA}/manage/purchasing/orders`);
  await page.getByRole("searchbox", { name: "Search purchase orders" }).fill(number);
  return page.getByRole("row", { name: new RegExp(number) });
}

test("global search opens a shop by its mobile and a list with the same search", async ({
  browser,
}) => {
  const { context, page } = await staff(browser, "sharma", "owner");
  const input = await openSearch(page, "9876500001");
  await expect(page.getByText("Best match")).toBeVisible();
  await input.press("Enter");
  await expect(page).toHaveURL(/\/manage\/retailers\/[0-9a-f-]+$/);
  await expect(page.getByText("Ganesh Kirana").first()).toBeVisible();

  await openSearch(page, "Parle");
  await page.getByRole("option", { name: /See all Products/ }).click();
  await expect(page).toHaveURL(/\/manage\/products\?q=Parle$/);
  await expect(page.getByRole("searchbox").first()).toHaveValue("Parle");
  await context.close();
});

test("a supplier, a purchase order emailed to them, and receiving more than ordered", async ({
  browser,
}) => {
  const { context, page } = await staff(browser, "sharma", "owner");
  const stamp = Date.now().toString(36);
  const supplier = `E2E Supplier ${stamp}`;
  const email = `po-${stamp}@supplier-e2e.example.com`;

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Purchasing" })
    .click();
  await expect(page.getByRole("heading", { name: "Purchase orders" })).toBeVisible();
  await page.goto(`${SHARMA}/manage/purchasing/suppliers/new`);
  await page.getByRole("textbox", { name: /^Name/ }).fill(supplier);
  await page.getByRole("textbox", { name: /^Email/ }).fill(email);
  await page.getByRole("textbox", { name: /^Delivery days/ }).fill("3");
  await page.getByRole("button", { name: "Add supplier" }).click();
  await expect(page).toHaveURL(/\/manage\/purchasing\/suppliers\/[0-9a-f-]+$/);

  // A draft for 10 of one product, at a cost before GST.
  await page.goto(`${SHARMA}/manage/purchasing/orders/new`);
  await page.getByRole("combobox", { name: "Supplier" }).click();
  await page.getByRole("option", { name: supplier }).click();
  const scan = page.getByLabel("Scan or search a product");
  await scan.fill("SH-0007");
  await scan.press("Enter"); // what a USB scanner does
  await page.getByLabel(/^Quantity of .+ in /).fill("10");
  await page.getByLabel(/^Cost of one /).fill("50");
  await page.getByRole("button", { name: "Save draft" }).click();
  const heading = page.getByRole("heading", { name: /^PO-\d{4}-\d{5}$/ });
  await expect(heading).toBeVisible();
  const number = (await heading.textContent())!.trim();
  await expect(page.getByText("₹500.00").first()).toBeVisible(); // 10 x 50, by the server

  // Sent: emailed with a link to the PDF, and a link to share on WhatsApp.
  await page.getByRole("button", { name: "Send to supplier" }).click();
  const confirm = page.getByRole("alertdialog");
  await expect(confirm.getByText(`It is emailed to ${email}`, { exact: false })).toBeVisible();
  await confirm.getByRole("button", { name: "Send to supplier" }).click();
  await expect(page.getByRole("link", { name: "Share on WhatsApp" })).toBeVisible();
  const link = await linkFromEmail(
    email,
    /https?:\/\/[^\s"<]+\/api\/v1\/public\/documents\/[^\s"<]+/,
  );
  await expect
    .poll(async () => (await page.request.get(link)).headers()["content-type"], {
      timeout: 60_000, // the worker makes the PDF
    })
    .toContain("application/pdf");
  await page.getByRole("button", { name: "Done" }).click();

  // 12 arrive against 10 ordered: beyond the 10% tolerance, so the owner confirms.
  await page.getByRole("button", { name: "Receive goods" }).click();
  await expect(page).toHaveURL(/\/manage\/stock\/inwards\/[0-9a-f-]+$/);
  await expect(page.getByRole("link", { name: number })).toBeVisible();
  await expect(page.getByText(/^Ordered 10 \w+, 0 received before$/)).toBeVisible();
  await page.getByLabel(/^Quantity of .+ in /).fill("12");
  await page.getByRole("button", { name: "Post", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Post" }).click();
  const over = page.getByRole("dialog", { name: "More than ordered" });
  await expect(over.getByText(/ordered 10, 0 received before, 12 now/)).toBeVisible();
  await over.getByRole("button", { name: "Receive anyway" }).click();
  await expect(page.getByRole("heading", { name: /^GRN-\d{4}-\d{5}$/ })).toBeVisible();

  const row = await orderRow(page, number);
  await expect(row.getByText("Received", { exact: true })).toBeVisible();
  await context.close();
});

test("a reorder suggestion, explained, becomes a draft purchase order", async ({ browser }) => {
  const { context, page } = await staff(browser, "sharma", "owner");
  await page.goto(`${SHARMA}/manage/stock`);
  await page
    .getByRole("navigation", { name: "Stock sections" })
    .getByRole("link", { name: "Reorder suggestions" })
    .click();
  await expect(page.getByRole("heading", { name: "Reorder suggestions" })).toBeVisible();
  const first = page.getByRole("row").nth(1);
  await expect(first.getByText(/^(Shops ordered|Little sales history)/)).toBeVisible();
  await first.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create purchase orders" }).click();
  const created = page.getByText(/^Draft purchase orders? .*PO-\d{4}-\d{5}/);
  await expect(created).toBeVisible();
  const number = (await created.textContent())!.match(/PO-\d{4}-\d{5}/)![0];

  const row = await orderRow(page, number);
  await expect(row.getByText("Draft", { exact: true })).toBeVisible();
  await context.close();
});

test("the salesperson gets no purchasing", async ({ browser }) => {
  const { context, page } = await staff(browser, "sharma", "sales");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: /^Orders/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Purchasing" })).toHaveCount(0);
  await context.close();
});

test("with the modules off, Patel sees no purchasing or stock planning", async ({ browser }) => {
  const { context, page } = await staff(browser, "patel", "owner");
  await expect(page.getByRole("heading", { name: "Needs action" })).toBeVisible();
  await expect(page.getByText("Products to reorder")).toHaveCount(0);
  await expect(page.getByText("Purchase orders late")).toHaveCount(0);
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: /^Stock/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Purchasing" })).toHaveCount(0);

  await openSearch(page, "purchase order");
  await expect(page.getByText(/Nothing found for “purchase order”/)).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(`${PATEL}/manage/stock`);
  const sections = page.getByRole("navigation", { name: "Stock sections" });
  await expect(sections.getByRole("link", { name: "Movements" })).toBeVisible();
  await expect(sections.getByRole("link", { name: "Reorder suggestions" })).toHaveCount(0);
  await page.goto(`${PATEL}/manage/stock/reorder`);
  await expect(page.getByText("Stock planning isn't switched on")).toBeVisible();
  await page.goto(`${PATEL}/manage/purchasing/orders`);
  await expect(page.getByText("Purchasing isn't switched on")).toBeVisible();
  await page.goto(`${PATEL}/manage/settings/business`);
  const settings = page.getByRole("navigation", { name: "Settings sections" });
  await expect(settings.getByRole("link", { name: "Reports" })).toBeVisible();
  await expect(settings.getByRole("link", { name: "Stock planning" })).toHaveCount(0);
  await expect(settings.getByRole("link", { name: "Purchasing" })).toHaveCount(0);
  await context.close();
});
