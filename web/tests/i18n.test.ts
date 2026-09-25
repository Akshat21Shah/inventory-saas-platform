import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import messages from "@/messages/en.json";

describe("i18n catalogue", () => {
  it("has a translated message for every backend error code", () => {
    const source = readFileSync(resolve(__dirname, "../../backend/common/error_codes.py"), "utf8");
    const codes = [...source.matchAll(/^\s+([A-Z_]+) = "([A-Z_]+)"$/gm)].map((m) => m[2]);
    expect(codes.length).toBeGreaterThan(10);
    const missing = codes.filter((code) => !(code! in messages.errors));
    expect(missing).toEqual([]);
  });
});
