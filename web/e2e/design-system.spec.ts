import { expect, test } from "@playwright/test";

test("design system renders core components without horizontal scroll", async ({ page }) => {
  await page.goto("/design-system");
  await expect(page.getByRole("heading", { name: "Design system", level: 1 })).toBeVisible();
  await expect(page.getByText("₹1,23,456.50").first()).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("retailer shell has bottom navigation with large targets", async ({ page }) => {
  // The offline page renders the shop shell without a session (service-worker fallback).
  await page.goto("/shop/offline");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const home = nav.getByRole("link", { name: "Home" });
  await expect(home).toBeVisible();
  const box = await home.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test("signed-out visitors to the shop are sent to sign in", async ({ page }) => {
  await page.goto("/shop");
  await expect(page).toHaveURL(/\/(shop\/)?login/);
});
