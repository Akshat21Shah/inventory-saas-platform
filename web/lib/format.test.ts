import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatMoney, formatQty } from "./format";

describe("formatMoney", () => {
  it.each([
    ["123456.5", "₹1,23,456.50"],
    ["0.01", "₹0.01"],
    ["12345678.90", "₹1,23,45,678.90"],
    ["1000", "₹1,000.00"],
  ])("formats %s as %s (Indian grouping, 2 decimals)", (input, expected) => {
    expect(formatMoney(input)).toBe(expected);
  });

  it("keeps precision beyond float range by formatting the decimal string", () => {
    expect(formatMoney("99999999999.99")).toBe("₹99,99,99,99,999.99");
  });

  it("rejects non-decimal input rather than guessing", () => {
    expect(() => formatMoney("12,00")).toThrow();
    expect(() => formatMoney("abc")).toThrow();
  });
});

describe("formatQty", () => {
  it("trims trailing zeros and uses Indian grouping", () => {
    expect(formatQty("1234.500")).toBe("1,234.5");
    expect(formatQty("2.750")).toBe("2.75");
    expect(formatQty("100000")).toBe("1,00,000");
  });
});

describe("dates are shown in Asia/Kolkata as DD-MM-YYYY", () => {
  it("rolls over the UTC date at IST midnight (FY boundary case)", () => {
    // 31-Mar 19:00 UTC is 01-Apr 00:30 IST
    expect(formatDate("2026-03-31T19:00:00Z")).toBe("01-04-2026");
    expect(formatDateTime("2026-03-31T19:00:00Z")).toBe("01-04-2026, 00:30");
  });

  it("rejects invalid dates", () => {
    expect(() => formatDate("not-a-date")).toThrow();
  });
});
