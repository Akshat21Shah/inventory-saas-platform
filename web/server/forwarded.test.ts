import { describe, expect, it } from "vitest";

import { createProxyMatcher, normalizeAddress, setForwardedHeaders } from "./forwarded.mjs";

type Headers = Record<string, string | string[] | undefined>;

const spoofed = (): Headers => ({
  host: "alpha.localhost:3000",
  "x-forwarded-for": "6.6.6.6",
  "x-forwarded-host": "admin.localhost",
  "x-forwarded-proto": "https",
  "x-forwarded-port": "443",
  forwarded: "for=6.6.6.6;proto=https",
  "x-real-ip": "6.6.6.6",
});

describe("setForwardedHeaders (ADR-032)", () => {
  it("replaces everything a browser sends with values from the connection", () => {
    const headers = spoofed();
    const client = setForwardedHeaders(
      headers,
      { remoteAddress: "203.0.113.5" },
      createProxyMatcher(""),
    );
    expect(client).toBe("203.0.113.5");
    expect(headers).toEqual({
      host: "alpha.localhost:3000",
      "x-forwarded-for": "203.0.113.5",
      "x-forwarded-host": "alpha.localhost:3000",
      "x-forwarded-proto": "http",
    });
  });

  it("a spoofed X-Forwarded-For never reaches the backend, whatever the value", () => {
    const isTrusted = createProxyMatcher("");
    const seen = new Set<string>();
    for (let i = 0; i < 20; i += 1) {
      const headers: Headers = { host: "alpha.localhost", "x-forwarded-for": `198.51.100.${i}` };
      setForwardedHeaders(headers, { remoteAddress: "203.0.113.5" }, isTrusted);
      seen.add(String(headers["x-forwarded-for"]));
    }
    expect([...seen]).toEqual(["203.0.113.5"]); // one client, one rate-limit bucket
  });

  it("behind a trusted load balancer, takes the rightmost untrusted address it appended", () => {
    const isTrusted = createProxyMatcher("10.0.0.0/8");
    const headers: Headers = {
      host: "alpha.example.com",
      "x-forwarded-for": "6.6.6.6, 198.51.100.7, 10.0.0.9",
      "x-forwarded-proto": "https",
    };
    const client = setForwardedHeaders(headers, { remoteAddress: "10.0.0.2" }, isTrusted);
    expect(client).toBe("198.51.100.7");
    expect(headers["x-forwarded-for"]).toBe("198.51.100.7");
    expect(headers["x-forwarded-proto"]).toBe("https");
  });

  it("ignores the proto and chain from an untrusted peer", () => {
    const headers: Headers = {
      host: "a",
      "x-forwarded-proto": "https",
      "x-forwarded-for": "1.1.1.1",
    };
    setForwardedHeaders(
      headers,
      { remoteAddress: "203.0.113.5", encrypted: false },
      createProxyMatcher("10.0.0.0/8"),
    );
    expect(headers["x-forwarded-proto"]).toBe("http");
    expect(headers["x-forwarded-for"]).toBe("203.0.113.5");
  });

  it("uses https for TLS connections and handles IPv4-mapped IPv6 peers", () => {
    const headers: Headers = { host: "a" };
    setForwardedHeaders(
      headers,
      { remoteAddress: "::ffff:192.0.2.4", encrypted: true },
      createProxyMatcher(""),
    );
    expect(headers["x-forwarded-for"]).toBe("192.0.2.4");
    expect(headers["x-forwarded-proto"]).toBe("https");
  });
});

describe("createProxyMatcher", () => {
  it("matches addresses and subnets, IPv4 and IPv6", () => {
    const isTrusted = createProxyMatcher("172.30.0.10, 10.0.0.0/8, fd00::/8");
    expect(isTrusted("172.30.0.10")).toBe(true);
    expect(isTrusted("::ffff:10.1.2.3")).toBe(true);
    expect(isTrusted("fd00::1")).toBe(true);
    expect(isTrusted("172.30.0.11")).toBe(false);
    expect(isTrusted("not-an-ip")).toBe(false);
  });

  it("rejects malformed configuration loudly", () => {
    expect(() => createProxyMatcher("not-an-ip")).toThrow(/TRUSTED_PROXIES/);
  });

  it("normalizes addresses", () => {
    expect(normalizeAddress(" ::ffff:127.0.0.1 ")).toBe("127.0.0.1");
    expect(normalizeAddress(undefined)).toBe("");
  });
});
