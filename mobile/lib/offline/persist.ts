/**
 * What's saved for use without a connection (ADR-061 item 10; owner's answer 5): categories and
 * brands, the catalogue pages and products seen, home (the usual products), the cart, the last 20
 * orders and bills, the statement's first page, payments and the account. At most 10 MB; the least
 * recently fetched go first. Product photos are cached separately (at most 50 MB, see
 * patches/expo-image+*.patch).
 */
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import type { Query } from "@tanstack/react-query";
import type { PersistedClient } from "@tanstack/react-query-persist-client";

import { APP_VERSION, config } from "@/lib/config";
import { fileStore } from "@/lib/storage/file-store";

export const SAVED_DATA_LIMIT = 10 * 1024 * 1024;
const MAX_DETAILS = 20; // orders and bills kept one by one
const WEEK = 7 * 24 * 60 * 60 * 1000;

const KEEP =
  /^\/api\/v1\/(shop\/(categories|brands|products|home|announcements|cart|orders|invoices|ledger|account|payments|distributor|addresses)\/|app\/config\/|public\/tenants\/)/;
const DETAIL = /^\/api\/v1\/shop\/(orders|invoices)\/[^/]+\/$/;

const keyOf = (query: { queryKey: readonly unknown[] }) => String(query.queryKey[0] ?? "");

/** Only what the shop has seen and needs offline; the statement only for its default dates. */
export function shouldSave(query: Query): boolean {
  const key = keyOf(query);
  // Data the shop has seen stays saved even when a later fetch failed (offline, signed out).
  if (query.state.data === undefined || !KEEP.test(key)) return false;
  if (key === "/api/v1/shop/ledger/") {
    const params = query.queryKey[1] as Record<string, unknown> | undefined;
    return !params || !Object.values(params).some(Boolean);
  }
  return true;
}

const bytes = (text: string) => new TextEncoder().encode(text).length;

/** The newest first, at most 20 orders and 20 bills, and within the size limit. */
export function trimToLimit(client: PersistedClient, limit = SAVED_DATA_LIMIT): PersistedClient {
  const newest = [...client.clientState.queries].sort(
    (a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt,
  );
  const details = new Map<string, number>();
  const kept: typeof newest = [];
  let size = bytes(JSON.stringify({ ...client, clientState: { mutations: [], queries: [] } }));
  for (const query of newest) {
    const key = keyOf(query);
    const kind = DETAIL.exec(key)?.[1];
    if (kind) {
      const count = details.get(kind) ?? 0;
      if (count >= MAX_DETAILS) continue;
      details.set(kind, count + 1);
    }
    const length = bytes(JSON.stringify(query)) + 1;
    if (size + length > limit) continue;
    size += length;
    kept.push(query);
  }
  return { ...client, clientState: { mutations: [], queries: kept } };
}

export const persister = createAsyncStoragePersister({
  storage: fileStore,
  key: "query-cache",
  throttleTime: 3000,
  serialize: (client) => JSON.stringify(trimToLimit(client)),
});

export const persistOptions = {
  persister,
  maxAge: WEEK,
  // A new version of the app starts without the old saved data.
  buster: `${APP_VERSION}+${config.build}`,
  dehydrateOptions: { shouldDehydrateQuery: shouldSave },
};
