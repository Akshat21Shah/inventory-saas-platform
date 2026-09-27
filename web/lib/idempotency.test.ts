import { describe, expect, it } from "vitest";

import { idempotent, newIdempotencyKey } from "./idempotency";

describe("idempotency keys", () => {
  it("are 32 hex characters, different every time, without crypto.randomUUID", () => {
    const original = crypto.randomUUID;
    // Plain-http pages (phones on the LAN) have no randomUUID.
    Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
    try {
      const keys = new Set(Array.from({ length: 50 }, newIdempotencyKey));
      expect(keys.size).toBe(50);
      for (const key of keys) expect(key).toMatch(/^[0-9a-f]{32}$/);
    } finally {
      Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
    }
    expect(idempotent("k")).toEqual({ headers: { "Idempotency-Key": "k" } });
  });
});
