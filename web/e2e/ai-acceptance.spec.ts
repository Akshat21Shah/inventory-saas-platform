import { expect, test, type Browser } from "@playwright/test";

import { signInAsSuperAdmin } from "./support/flows";
import { FULL_STACK, OTP_CODE, origin, resetLimits } from "./support/stack";

/**
 * Phase 9d acceptance (ADR-058) on the seeded demo business (Sharma Distributors has the AI module
 * on, with the local mock provider):
 * - a shop's misspelt search ("biscuts") finds biscuits by meaning, where words alone find none;
 * - the owner sees this month's AI use on the Modules page;
 * - the super admin sees Sharma's AI use on the dashboard.
 * Similarity, limits and fallbacks are the server's (backend tests prove them). Needs the full
 * stack (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.skip(({ isMobile }) => isMobile, "desktop flows; the responsive sweep covers phones");
test.describe.configure({ mode: "serial", timeout: 300_000 });

const SHARMA = origin("sharma");
const SHOP_PHONE = "9876500001";

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

test("a shop's misspelt search finds products by meaning", async ({ browser }) => {
  const { context, page } = await shop(browser);
  await page.goto(`${SHARMA}/shop/search?q=biscuts`);
  await expect(page.getByText(/nothing found/i)).toHaveCount(0);
  // The demo's biscuits (Hide & Seek, Tiger, Treat, Good Day, Marie …) under "Biscuits".
  await expect(
    page.getByRole("link", { name: /Hide & Seek|Tiger|Treat|Good Day|Marie|Bourbon/ }).first(),
  ).toBeVisible();
  await context.close();
});

test("the owner and the super admin see this month's AI use", async ({ browser, page }) => {
  const email = "owner@sharma.example.com";
  resetLimits({ emails: [email] });
  const context = await browser.newContext();
  const owner = await context.newPage();
  await owner.goto(`${SHARMA}/login`);
  await owner.getByLabel(/email address/i).fill(email);
  await owner.getByLabel(/^password/i).fill("staff-dev-password");
  await owner.getByRole("button", { name: /^sign in$/i }).click();
  await owner.waitForURL(`${SHARMA}/manage`);
  await owner.goto(`${SHARMA}/manage/settings/features`);
  const usage = owner.getByRole("region", { name: "AI use this month" });
  await expect(usage.getByText(/ of [\d,]+ units$/)).toBeVisible();
  await expect(usage.getByText("Shop search: what shops typed")).toBeVisible();
  await context.close();

  await signInAsSuperAdmin(page);
  const section = page.getByRole("region", { name: "AI use this month" });
  await expect(section.getByRole("link", { name: "Sharma Distributors" }).first()).toBeVisible();
});
