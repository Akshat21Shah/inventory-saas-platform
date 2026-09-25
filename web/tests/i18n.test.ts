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

  it("has a label and plain-language description for every setting in the registry (§9.3)", () => {
    const source = readFileSync(
      resolve(__dirname, "../../backend/apps/platform/registry.py"),
      "utf8",
    );
    const keys = [...source.matchAll(/_(?:tenant|platform)\("([a-z_]+\.[a-z0-9_]+)"/g)].map(
      (m) => m[1]!,
    );
    expect(keys.length).toBeGreaterThan(30);
    const catalogue = messages.settings as Record<
      string,
      Record<string, { label?: string; description?: string }>
    >;
    const missing = keys.filter((key) => {
      const [ns, name] = key.split(".") as [string, string];
      const entry = catalogue[ns]?.[name];
      return !entry?.label || !entry?.description;
    });
    expect(missing).toEqual([]);
  });
});
