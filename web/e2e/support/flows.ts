import { expect, type Page } from "@playwright/test";

import { ADMIN, linkFromEmail, origin, randomGstin, resetLimits, totp } from "./stack";

/** Signs in as the seeded super admin (password + the dev 2FA key). */
export async function signInAsSuperAdmin(page: Page) {
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

export interface NewDistributor {
  slug: string;
  name: string;
  ownerEmail: string;
  ownerPassword: string;
}

export function newDistributor(stamp: string): NewDistributor {
  return {
    slug: `e2e-${stamp}`,
    name: `E2E Traders ${stamp}`,
    ownerEmail: `owner-${stamp}@e2e.example.com`,
    ownerPassword: "a-long-e2e-owner-passphrase",
  };
}

/** The super admin runs the onboarding wizard; the owner's invitation goes out. */
export async function createDistributor(page: Page, d: NewDistributor) {
  await signInAsSuperAdmin(page);
  await page.goto(`${origin("admin")}/platform/tenants/new`);
  const next = () => page.getByRole("button", { name: /^next$/i }).click();

  await page.getByLabel(/^business name/i).fill(d.name);
  await page.getByLabel(/^legal name/i).fill(`${d.name} LLP`);
  await page.getByLabel(/^business email/i).fill(`office-${d.slug}@e2e.example.com`);
  await page.getByLabel(/^business phone/i).fill("9876543210");
  await next();
  await page.getByLabel(/^gstin/i).fill(randomGstin());
  await page.getByLabel(/^address line 1/i).fill("1 Test Road");
  await page.getByLabel(/^city/i).fill("Pune");
  await page.getByLabel(/^pin code/i).fill("411001");
  await next();
  await page.getByLabel(/^owner's email/i).fill(d.ownerEmail);
  await next();
  await page.getByLabel(/^web address/i).fill(d.slug);
  await expect(page.getByText(/this web address is available/i)).toBeVisible();
  await next();
  await next();
  await page.getByRole("button", { name: /create distributor/i }).click();
  await expect(page.getByRole("heading", { name: d.name })).toBeVisible();
}

/** The owner opens the emailed invitation, sets a password and lands in the panel. */
export async function acceptOwnerInvitation(page: Page, d: NewDistributor) {
  const link = await linkFromEmail(d.ownerEmail, /https?:\/\/[^\s"<>]+\/invite\/[^\s"<>]+/);
  expect(new URL(link).host).toBe(new URL(origin(d.slug)).host);
  await page.goto(link);
  await page.getByLabel(/^your name/i).fill("E2E Owner");
  await page.getByLabel(/^new password/i).fill(d.ownerPassword);
  await page.getByRole("button", { name: /accept invitation/i }).click();
  await page.waitForURL(`${origin(d.slug)}/manage**`);
}

/** Staff sign-in with email and password on the distributor's address. */
export async function signInAsOwner(page: Page, d: NewDistributor) {
  resetLimits({ emails: [d.ownerEmail] });
  await page.goto(`${origin(d.slug)}/login`);
  await page.getByLabel(/email address/i).fill(d.ownerEmail);
  await page.getByLabel(/^password/i).fill(d.ownerPassword);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(`${origin(d.slug)}/manage`);
}
