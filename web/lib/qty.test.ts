import { describe, expect, it } from "vitest";

import { firstQty, fromMilli, isZero, nextQty, previousQty, toMilli } from "./qty";

describe("quantity steps", () => {
  it("reads and writes quantities as whole thousandths", () => {
    expect(toMilli("12.5")).toBe(12500);
    expect(toMilli("0.125")).toBe(125);
    expect(toMilli("1.2345")).toBeNull();
    expect(toMilli("-1")).toBeNull();
    expect(toMilli("abc")).toBeNull();
    expect(fromMilli(12500)).toBe("12.5");
    expect(fromMilli(3000)).toBe("3");
    expect(fromMilli(1)).toBe("0.001");
  });

  it("starts at the minimum, rounded up to the multiple", () => {
    expect(firstQty("1.000", "1.000")).toBe("1");
    expect(firstQty("5", "1")).toBe("5");
    expect(firstQty("5", "6")).toBe("6");
    expect(firstQty("10", "6")).toBe("12");
    expect(firstQty("0", "0.5")).toBe("0.5");
  });

  it("steps by the multiple and drops to 0 below the minimum", () => {
    expect(nextQty("0", "5", "1")).toBe("5");
    expect(nextQty("5", "5", "1")).toBe("6");
    expect(nextQty("12", "10", "6")).toBe("18");
    expect(nextQty("13", "10", "6")).toBe("18"); // back onto the multiple
    expect(previousQty("6", "5", "1")).toBe("5");
    expect(previousQty("5", "5", "1")).toBe("0");
    expect(previousQty("18", "10", "6")).toBe("12");
    expect(previousQty("12", "10", "6")).toBe("0");
    expect(previousQty("1.5", "0", "0.5")).toBe("1");
  });

  it("knows zero", () => {
    expect(isZero("0")).toBe(true);
    expect(isZero("0.000")).toBe(true);
    expect(isZero("0.001")).toBe(false);
  });
});
