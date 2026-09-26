import { expect, test } from "@playwright/test";

import { acceptOwnerInvitation, createDistributor, newDistributor } from "./support/flows";
import {
  FULL_STACK,
  OTP_CODE,
  linkFromEmail,
  origin,
  resetLimits,
  SHOP_PHONES,
} from "./support/stack";

/**
 * Phase 1 acceptance (spec §12): the super admin creates a distributor; its owner accepts the
 * invitation, signs in, sets branding and invites staff; the branding shows on the tenant's
 * sign-in page. Plus retailer OTP sign-in on a subdomain and through the generic chooser.
 * Needs the full stack and `make seed` (E2E_FULL_STACK=1).
 */
test.skip(!FULL_STACK, "needs the full stack (E2E_FULL_STACK=1)");
test.describe.configure({ mode: "serial", timeout: 120_000 });

test.describe("distributor onboarding", () => {
  test.skip(({ isMobile }) => isMobile, "desktop flow");

  const stamp = Date.now().toString(36);
  const distributor = newDistributor(stamp);
  const { slug, name, ownerEmail, ownerPassword } = distributor;

  test("super admin creates a distributor and the owner is invited", async ({ page }) => {
    await createDistributor(page, distributor);
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByText("Onboarding", { exact: true })).toBeVisible();
    await expect(page.getByText(/invitation sent, not accepted yet/i)).toBeVisible();
  });

  test("the owner accepts, sets branding and invites staff", async ({ page }) => {
    await acceptOwnerInvitation(page, distributor);

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
