import { expect, test } from "@playwright/test";

test("design system renders core components without horizontal scroll", async ({ page }) => {
  await page.goto("/design-system");
  await expect(page.getByRole("heading", { name: "Design system", level: 1 })).toBeVisible();
  await expect(page.getByText("₹1,23,456.50").first()).toBeVisible();
  // Lists are tables on laptops and cards below 1024 px (CLAUDE.md §6a).
  const width = page.viewportSize()?.width ?? 1280;
  if (width >= 1024) await expect(page.getByRole("table")).toBeVisible();
  else await expect(page.getByRole("table")).toHaveCount(0);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("retailer shell navigation: bottom bar with large targets on phones, header on laptops", async ({
  page,
}) => {
  // The offline page renders the shop shell without a session (service-worker fallback).
  await page.goto("/shop/offline");
  const width = page.viewportSize()?.width ?? 1280;
  const home = page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", {
    name: "Home",
  });
  await expect(home).toBeVisible();
  const box = await home.boundingBox();
  if (width < 1024) {
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.y ?? 0).toBeGreaterThan((page.viewportSize()?.height ?? 0) / 2); // at the bottom
  } else {
    expect(box?.y ?? 999).toBeLessThan(60); // in the header
  }
});

test("signed-out visitors to the shop are sent to sign in", async ({ page }) => {
  await page.goto("/shop");
  await expect(page).toHaveURL(/\/(shop\/)?login/);
});
