import { describe, expect, it } from "vitest";

import { handoffUrl, homeFor, platformDomainFrom, safeNext, tenantOrigin } from "./urls";

describe("sign-in URLs", () => {
  it("finds the platform domain from any host", () => {
    expect(platformDomainFrom("admin.localhost")).toBe("localhost");
    expect(platformDomainFrom("www.example.com")).toBe("example.com");
    expect(platformDomainFrom("example.com")).toBe("example.com");
    expect(platformDomainFrom("sharma.example.com", "sharma")).toBe("example.com");
  });

  it("builds tenant origins and puts handoff codes in the fragment only", () => {
    const location = { protocol: "http:", hostname: "localhost", port: "3000" } as Location;
    expect(tenantOrigin("sharma", location)).toBe("http://sharma.localhost:3000");
    window.history.replaceState(null, "", "/login");
    const url = new URL(handoffUrl("sharma", "abc123", "/shop"));
    expect(url.search).toBe("");
    expect(new URLSearchParams(url.hash.slice(1)).get("code")).toBe("abc123");
    expect(url.pathname).toBe("/auth/handoff");
  });

  it("accepts only same-site relative paths as the destination", () => {
    expect(safeNext("/manage/settings", "/x")).toBe("/manage/settings");
    expect(safeNext("//evil.example.com", "/x")).toBe("/x");
    expect(safeNext("https://evil.example.com", "/x")).toBe("/x");
    expect(safeNext(null, "/x")).toBe("/x");
  });

  it("sends each account type to its own area", () => {
    expect(homeFor("PLATFORM")).toBe("/platform");
    expect(homeFor("STAFF")).toBe("/manage");
    expect(homeFor("RETAILER")).toBe("/shop");
  });
});
