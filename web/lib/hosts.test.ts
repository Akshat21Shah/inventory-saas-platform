import { describe, expect, it } from "vitest";

import { classifyHost } from "./hosts";

describe("classifyHost mirrors the backend rules", () => {
  it.each([
    ["localhost:3000", "GENERIC", null],
    ["admin.localhost", "ADMIN", null],
    ["sharma.localhost:3000", "TENANT", "sharma"],
    ["Sharma.LOCALHOST", "TENANT", "sharma"],
    ["www.localhost", "GENERIC", null],
    ["api.localhost", "UNKNOWN", null],
    ["a.b.localhost", "UNKNOWN", null],
    ["evil.com", "UNKNOWN", null],
    ["-bad.localhost", "UNKNOWN", null],
  ])("%s → %s", (host, kind, slug) => {
    expect(classifyHost(host, "localhost")).toEqual({ kind, tenantSlug: slug });
  });
});
