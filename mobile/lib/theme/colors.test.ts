import { colors as tokens } from "@/lib/shared/tokens";

import { colorsFor, oklchToHex } from "./colors";

describe("colours", () => {
  it("converts the web's OKLCH colours", () => {
    expect(oklchToHex("oklch(1 0 0)")).toBe("#ffffff");
    expect(oklchToHex("oklch(0.145 0 0)")).toBe(tokens.foreground);
  });

  it("applies the distributor's brand", () => {
    const green = colorsFor("#1a7f37");
    expect(green.primary).toBe("#1a7f37");
    expect(green.primaryForeground).toBe("#fafafa"); // readable on a dark green
    expect(green.brand50).not.toBe(colorsFor(null).brand50);
    expect(green.background).toBe(tokens.background); // the rest stays the web's
  });

  it("falls back to the platform's colour", () => {
    expect(colorsFor("not a colour").primary).toBe(colorsFor(null).primary);
  });
});
