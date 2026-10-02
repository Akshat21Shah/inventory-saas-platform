import { expect, test, type Browser } from "@playwright/test";

import { signInAsSuperAdmin } from "./support/flows";
import { FULL_STACK, origin, resetLimits } from "./support/stack";

/**
 * Phase 8 acceptance (spec 5.14, ADR-050) on the seeded demo business:
 * - the owner's dashboard opens on what needs action, then today and the last 30 days;
 * - the sales register (sales by invoice) for a chosen period, each row leading to its invoice,
 *   exported to Excel at once;
 * - the GST workbook, always made in the background by the reports worker: "Report ready" in the
 *   app and a download from My exports;
 * - the warehouse sees stock reports but no sales, even by typing the address;
 * - the super admin's dashboard shows orders across distributors, the top ones and usage.
 * Figures are the server's (backend tests prove them). Needs the full stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SHARMA = origin("sharma");

async function staff(browser: Browser, role: string) {
  const email = `${role}@sharma.example.com`;
  resetLimits({ emails: [email] });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  await page.goto(`${SHARMA}/login`);
  await page.getByLabel(/email address/i).fill(email);
  await page.getByLabel(/^password/i).fill("staff-dev-password");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${SHARMA}/manage`);
  return { context, page };
}

/** yyyy-mm-dd in India, `days` ago. */
function istDate(days = 0): string {
  const now = new Date(Date.now() - days * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(now);
}

test("the owner's dashboard, the sales register and its Excel file", async ({ browser }) => {
  const { context, page } = await staff(browser, "owner");
  await expect(page.getByRole("heading", { name: "Needs action" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Today so far" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Last 30 days" })).toBeVisible();

  await page.getByRole("link", { name: "All reports" }).click();
  await page.getByRole("link", { name: /Sales by invoice/ }).click();
  await expect(page.getByRole("heading", { name: "Sales by invoice" })).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill(istDate(60));
  const first = page.getByRole("link", { name: /^INV\// }).first();
  await expect(first).toBeVisible();
  await expect(page.getByRole("region", { name: "Totals" })).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export to Excel" }).click();
  const excel = await download;
  expect(excel.suggestedFilename()).toMatch(/^sales-by-invoice-\d{8}-\d{8}\.xlsx$/);
  expect(await excel.failure()).toBeNull(); // the file actually arrived

  const number = (await first.textContent())!.trim();
  await first.click();
  await expect(page).toHaveURL(/\/manage\/invoices\/[0-9a-f-]+$/);
  await expect(page.getByText(number).first()).toBeVisible();
  await context.close();
});

test("the GST workbook is made in the background and downloaded from My exports", async ({
  browser,
}) => {
  const { context, page } = await staff(browser, "owner");
  await page.goto(`${SHARMA}/manage/reports/gst_summary`);
  await expect(page.getByText(/prepared in the background/)).toBeVisible();
  await page.getByRole("button", { name: "Export to Excel" }).click();
  await expect(page.getByText(/We're preparing your file/)).toBeVisible();
  await page.getByRole("button", { name: "My exports" }).click();
  await expect(page).toHaveURL(`${SHARMA}/manage/reports/exports`);

  const row = page.getByRole("button", { name: /^Download gst-summary-/ }).first();
  await expect(row).toBeVisible({ timeout: 90_000 }); // the reports worker makes it
  const download = page.waitForEvent("download");
  await row.click();
  const workbook = await download;
  expect(workbook.suggestedFilename()).toMatch(/^gst-summary-.*\.xlsx$/);
  expect(await workbook.failure()).toBeNull(); // the file actually arrived

  await page.goto(`${SHARMA}/manage/notifications`);
  await expect(page.getByText("Report ready").first()).toBeVisible();
  await context.close();
});

test("the warehouse gets stock reports and no sales", async ({ browser }) => {
  const { context, page } = await staff(browser, "warehouse");
  await page.goto(`${SHARMA}/manage/reports`);
  await expect(page.getByRole("heading", { name: "Stock" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sales" })).toHaveCount(0);
  await page.goto(`${SHARMA}/manage/reports/sales_by_invoice`);
  await expect(page.getByText("This report isn't available")).toBeVisible();
  await context.close();
});

test("the super admin sees the platform's health", async ({ page }) => {
  await signInAsSuperAdmin(page);
  await expect(page.getByRole("heading", { name: "Orders across distributors" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Top distributors" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Usage against plans" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sharma Distributors" }).first()).toBeVisible();
});
