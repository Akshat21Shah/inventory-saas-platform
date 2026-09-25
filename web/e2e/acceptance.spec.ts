import { expect, test, type Page } from "@playwright/test";

import {
  ADMIN,
  FULL_STACK,
  OTP_CODE,
  linkFromEmail,
  origin,
  randomGstin,
  resetLimits,
  SHOP_PHONES,
  totp,
} from "./support/stack";

/**
 * Phase 1 acceptance (spec §12): the super admin creates a distributor; its owner accepts the
 * invitation, signs in, sets branding and invites staff; the branding shows on the tenant's
 * sign-in page. Plus retailer OTP sign-in on a subdomain and through the generic chooser.
 * Needs the full stack and `make seed` (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function signInAsSuperAdmin(page: Page) {
  // Each code is accepted once (replay protection); a retry reuses the current code, so clear the
  // account's replay state and counters first instead of waiting for the next 30-second step.
  resetLimits({ emails: [ADMIN.email] });
  await page.goto(`${origin("admin")}/login`);
  await page.getByLabel(/email address/i).fill(ADMIN.email);
  await page.getByLabel(/^password/i).fill(ADMIN.password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.getByLabel(/6-digit code/i).fill(totp(ADMIN.totpSecret));
  await page.getByRole("button", { name: /verify/i }).click();
  await page.waitForURL(`${origin("admin")}/platform`);
}

test.describe("distributor onboarding", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow");

  const stamp = Date.now().toString(36);
  const slug = `e2e-${stamp}`;
  const name = `E2E Traders ${stamp}`;
  const ownerEmail = `owner-${stamp}@e2e.example.com`;
  const ownerPassword = "a-long-e2e-owner-passphrase";

  test("super admin creates a distributor and the owner is invited", async ({ page }) => {
    await signInAsSuperAdmin(page);
    await page.goto(`${origin("admin")}/platform/tenants/new`);
    const next = () => page.getByRole("button", { name: /^next$/i }).click();

    await page.getByLabel(/^business name/i).fill(name);
    await page.getByLabel(/^legal name/i).fill(`${name} LLP`);
    await page.getByLabel(/^business email/i).fill(`office-${stamp}@e2e.example.com`);
    await page.getByLabel(/^business phone/i).fill("9876543210");
    await next();
    await page.getByLabel(/^gstin/i).fill(randomGstin());
    await page.getByLabel(/^address line 1/i).fill("1 Test Road");
    await page.getByLabel(/^city/i).fill("Pune");
    await page.getByLabel(/^pin code/i).fill("411001");
    await next();
    await page.getByLabel(/^owner's email/i).fill(ownerEmail);
    await next();
    await page.getByLabel(/^web address/i).fill(slug);
    await expect(page.getByText(/this web address is available/i)).toBeVisible();
    await next();
    await next();
    await page.getByRole("button", { name: /create distributor/i }).click();

    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByText("Onboarding", { exact: true })).toBeVisible();
    await expect(page.getByText(/invitation sent, not accepted yet/i)).toBeVisible();
  });

  test("the owner accepts, sets branding and invites staff", async ({ page }) => {
    const link = await linkFromEmail(ownerEmail, /https?:\/\/[^\s"<>]+\/invite\/[^\s"<>]+/);
    expect(new URL(link).host).toBe(new URL(origin(slug)).host);
    await page.goto(link);
    await page.getByLabel(/^your name/i).fill("E2E Owner");
    await page.getByLabel(/^new password/i).fill(ownerPassword);
    await page.getByRole("button", { name: /accept invitation/i }).click();
    await page.waitForURL(`${origin(slug)}/manage**`);

    // Branding: the saved colour applies at once.
    await page.goto(`${origin(slug)}/manage/settings/branding`);
    await page.getByLabel(/^display name/i).fill(`${name} Wholesale`);
    await page.getByLabel(/colour code/i).fill("#c2410c");
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByText(/branding saved/i)).toBeVisible();
    const primary = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--primary"),
    );
    expect(primary).toContain(" 38."); // orange hue, not the default blue (≈ 265)

    // Staff invitation.
    await page.goto(`${origin(slug)}/manage/settings/staff`);
    await page.getByRole("button", { name: /invite staff/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^email/i).fill(`sales-${stamp}@e2e.example.com`);
    await dialog.getByRole("button", { name: /send invitation/i }).click();
    await expect(page.getByRole("cell", { name: `sales-${stamp}@e2e.example.com` })).toBeVisible();
    await linkFromEmail(`sales-${stamp}@e2e.example.com`, /\/invite\/[^\s"<>]+/);
  });

  test("the tenant sign-in page shows the new branding, and the owner can sign in", async ({
    page,
  }) => {
    await page.goto(`${origin(slug)}/login`);
    await expect(page.getByText(`${name} Wholesale`).first()).toBeVisible();
    await page.getByLabel(/email address/i).fill(ownerEmail);
    await page.getByLabel(/^password/i).fill(ownerPassword);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL(`${origin(slug)}/manage`);
  });
});

test.describe("shop owner sign-in", () => {
  test.skip(({ isMobile }) => !isMobile, "phone flow");
  test.beforeEach(() => resetLimits({ phones: SHOP_PHONES }));

  test("with a one-time code on the distributor's address", async ({ page }) => {
    await page.goto(`${origin("sharma")}/shop/login`);
    await page.getByLabel(/mobile number/i).fill("9876500001");
    await page.getByRole("button", { name: /send code/i }).click();
    await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL(`${origin("sharma")}/shop`);
  });

  test("on the main address, choosing between two distributors", async ({ page }) => {
    await page.goto(`${origin()}/login`);
    await page.getByLabel(/mobile number/i).fill("9876500000");
    await page.getByRole("button", { name: /send code/i }).click();
    await page.getByLabel(/6-digit code/i).fill(OTP_CODE);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.getByRole("button", { name: /patel traders/i }).click();
    await page.waitForURL(`${origin("patel")}/shop`);
  });
});
