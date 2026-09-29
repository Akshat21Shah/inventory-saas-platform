import { expect, type Page } from "@playwright/test";

import {
  ADMIN,
  explainRefusal,
  freshTotp,
  linkFromEmail,
  origin,
  randomGstin,
  resetLimits,
} from "./stack";

/**
 * Signs in as the seeded super admin (password + the dev 2FA key). The code comes from
 * `freshTotp`, so it is computed for the backend's clock and never reuses a step; a refusal fails
 * at once with the reason (replay, clock skew or invalid) instead of timing out.
 */
export async function signInAsSuperAdmin(page: Page, { reset = true } = {}) {
  // Counters and lockouts (and, unless reset is false, the 2FA replay state).
  if (reset) resetLimits({ emails: [ADMIN.email] });
  await page.goto(`${origin("admin")}/login`);
  await page.getByLabel(/email address/i).fill(ADMIN.email);
  await page.getByLabel(/^password/i).fill(ADMIN.password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  const field = page.getByLabel(/6-digit code/i);
  await field.waitFor();
  const sent = await freshTotp(ADMIN.totpSecret, ADMIN.email);
  await field.fill(sent.code);
  await page.getByRole("button", { name: /verify/i }).click();
  const refused = page.getByText(/that code didn't work/i);
  const outcome = await Promise.race([
    page.waitForURL(`${origin("admin")}/platform`).then(() => "signed-in" as const),
    refused.waitFor().then(() => "refused" as const),
  ]);
  if (outcome === "refused") {
    throw new Error(`Super admin 2FA code refused: ${explainRefusal(sent, ADMIN.email)}`);
  }
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

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** Imports a workbook (add new only) and waits until every row is in. */
export async function importFile(
  page: Page,
  d: NewDistributor,
  kind: string,
  file: Buffer,
  rows: string,
) {
  await page.goto(`${origin(d.slug)}/manage/imports/new?kind=${kind}`);
  await page.getByRole("radio", { name: /^add new only/i }).check();
  await page.getByLabel(/choose an excel or csv file/i).setInputFiles({
    name: `${kind.toLowerCase()}.xlsx`,
    mimeType: XLSX,
    buffer: file,
  });
  await page.getByRole("button", { name: /check the file/i }).click();
  const label = `Import ${rows} ${rows === "1" ? "row" : "rows"}`;
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: label }).click();
  await expect(page.getByText(`${rows} ${rows === "1" ? "row" : "rows"} imported.`)).toBeVisible({
    timeout: 120_000,
  });
}

/** Receives stock of one product on a posted goods receipt. */
export async function receive(
  page: Page,
  d: NewDistributor,
  code: string,
  name: string,
  qty: string,
) {
  await page.goto(`${origin(d.slug)}/manage/stock/inwards/new`);
  await page.getByLabel("Supplier", { exact: true }).fill("E2E Wholesale");
  const scan = page.getByLabel("Scan or search a product");
  await scan.fill(code);
  await scan.press("Enter");
  const field = page.getByLabel(`Quantity of ${name} in PCS`);
  await field.fill(qty);
  await field.press("Enter");
  await page.getByRole("button", { name: "Save and post" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Post" }).click();
  await expect(page.getByRole("heading", { name: /^GRN-\d{4}-\d{5}$/ })).toBeVisible();
}
