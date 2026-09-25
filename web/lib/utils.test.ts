import { describe, expect, it } from "vitest";

import { formatIndianMobile, omitKey } from "./utils";

describe("formatIndianMobile", () => {
  it("groups an Indian mobile number for reading", () => {
    expect(formatIndianMobile("+919876543210")).toBe("+91 98765 43210");
  });

  it("leaves anything else as it is", () => {
    expect(formatIndianMobile("02024451234")).toBe("02024451234");
  });
});

describe("omitKey", () => {
  it("returns a copy without the key", () => {
    const source = { a: 1, b: 2 };
    expect(omitKey(source, "a")).toEqual({ b: 2 });
    expect(source).toEqual({ a: 1, b: 2 });
  });
});
