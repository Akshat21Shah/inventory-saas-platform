/**
 * A product's details from what the app has already fetched (ADR-061 item 10): the cart shows a
 * product added while offline by its name and photo before the server's cart has it.
 */
import type { QueryClient } from "@tanstack/react-query";

import type { ShopProduct } from "@/lib/api/generated/model";

type Page = { data?: { results?: ShopProduct[] } };

export function savedProduct(client: QueryClient, id: string): ShopProduct | undefined {
  for (const query of client.getQueryCache().getAll()) {
    const key = String(query.queryKey[0] ?? "");
    if (!key.startsWith("/api/v1/shop/products/")) continue;
    const data = query.state.data as
      { pages?: Page[]; data?: ShopProduct & { results?: ShopProduct[] } } | undefined;
    if (!data) continue;
    if (data.data && "id" in data.data && data.data.id === id) return data.data;
    const lists = [
      data.data?.results ?? [],
      ...(data.pages ?? []).map((p) => p.data?.results ?? []),
    ];
    for (const list of lists) {
      const found = list.find((product) => product.id === id);
      if (found) return found;
    }
  }
  return undefined;
}
