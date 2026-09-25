import { describe, expect, it } from "vitest";

import { brandCssVariables, brandStyleSheet, DEFAULT_BRAND_COLOR, hexToOklch } from "./palette";

describe("hexToOklch", () => {
  it("converts reference colours", () => {
    expect(hexToOklch("#ffffff").l).toBeCloseTo(1, 3);
    expect(hexToOklch("#000000").l).toBeCloseTo(0, 3);
    const red = hexToOklch("#ff0000");
    expect(red.l).toBeCloseTo(0.628, 2);
    expect(red.c).toBeCloseTo(0.258, 2);
    expect(red.h).toBeCloseTo(29.2, 0);
  });

  it("rejects invalid colours", () => {
    expect(() => hexToOklch("red")).toThrow();
  });
});

describe("brandCssVariables", () => {
  it("derives a full 50–950 scale with descending lightness", () => {
    const vars = brandCssVariables("#0f766e");
    const steps = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
    const lightness = steps.map((step) =>
      Number(/oklch\(([\d.]+)/.exec(vars[`--brand-${step}`] ?? "")?.[1]),
    );
    expect(lightness).toEqual([...lightness].sort((a, b) => b - a));
    expect(vars["--primary"]).toMatch(/^oklch\(/);
  });

  it("picks readable foreground text for light and dark brand colours", () => {
    expect(brandCssVariables("#1e3a8a")["--primary-foreground"]).toBe("oklch(0.985 0 0)");
    expect(brandCssVariables("#fde047")["--primary-foreground"]).toBe("oklch(0.18 0 0)");
  });

  it("falls back to the default brand for invalid input (no CSS injection)", () => {
    expect(brandStyleSheet("red;}body{display:none")).toBe(brandStyleSheet(DEFAULT_BRAND_COLOR));
  });
});
