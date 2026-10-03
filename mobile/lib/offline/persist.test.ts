import type { PersistedClient } from "@tanstack/react-query-persist-client";

import { shouldSave, trimToLimit } from "./persist";

jest.mock("@/lib/storage/file-store", () => ({ fileStore: {} }));

type Saved = PersistedClient["clientState"]["queries"][number];

const query = (key: string, at: number, params?: Record<string, unknown>, size = 10): Saved =>
  ({
    queryKey: params ? [key, params] : [key],
    queryHash: `${key}${JSON.stringify(params ?? {})}${at}`,
    state: { data: { data: "x".repeat(size) }, dataUpdatedAt: at, status: "success" },
  }) as unknown as Saved;

const client = (queries: Saved[]): PersistedClient => ({
  timestamp: 0,
  buster: "",
  clientState: { mutations: [], queries },
});

describe("What's saved for offline use", () => {
  it("keeps the newest first, at most 20 orders and 20 bills", () => {
    const orders = Array.from({ length: 25 }, (_, i) => query(`/api/v1/shop/orders/o${i}/`, i));
    const bills = Array.from({ length: 22 }, (_, i) => query(`/api/v1/shop/invoices/i${i}/`, i));
    const kept = trimToLimit(client([...orders, ...bills, query("/api/v1/shop/home/", 1)]))
      .clientState.queries;
    const keys = kept.map((q) => String(q.queryKey[0]));
    expect(keys.filter((k) => k.startsWith("/api/v1/shop/orders/"))).toHaveLength(20);
    expect(keys.filter((k) => k.startsWith("/api/v1/shop/invoices/"))).toHaveLength(20);
    expect(keys).toContain("/api/v1/shop/orders/o24/"); // the newest stay
    expect(keys).not.toContain("/api/v1/shop/orders/o0/"); // the oldest go
    expect(keys).toContain("/api/v1/shop/home/");
  });

  it("stays within the size limit, dropping the least recently fetched", () => {
    const queries = Array.from({ length: 10 }, (_, i) =>
      query(`/api/v1/shop/products/p${i}/`, i, undefined, 1000),
    );
    const kept = trimToLimit(client(queries), 5000).clientState.queries;
    expect(JSON.stringify(kept).length).toBeLessThan(5000);
    expect(kept.map((q) => q.state.dataUpdatedAt)).toEqual([9, 8, 7, 6]);
  });

  it("saves the shop's own pages, and the statement only for its default dates", () => {
    const of = (key: string, params?: Record<string, unknown>, status = "success") =>
      ({
        queryKey: params ? [key, params] : [key],
        state: { status, data: { data: {} } },
      }) as never;
    expect(shouldSave(of("/api/v1/shop/products/", { search: "" }))).toBe(true);
    expect(shouldSave(of("/api/v1/shop/ledger/"))).toBe(true);
    expect(shouldSave(of("/api/v1/shop/ledger/", { date_from: "2026-04-01" }))).toBe(false);
    expect(shouldSave(of("/api/v1/shop/notifications/"))).toBe(false);
    expect(shouldSave(of("/api/v1/auth/me/"))).toBe(false);
    // A later fetch that failed (offline, or before the session was renewed) keeps what was seen.
    expect(shouldSave(of("/api/v1/shop/cart/", undefined, "error"))).toBe(true);
    expect(
      shouldSave({ queryKey: ["/api/v1/shop/cart/"], state: { status: "pending" } } as never),
    ).toBe(false);
  });
});
