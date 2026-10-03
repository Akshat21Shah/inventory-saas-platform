"use client";

import { Search } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Input } from "@/components/ui/input";
import { useRetailersList } from "@/lib/api/generated/endpoints/retailers/retailers";
import type { RetailerList } from "@/lib/api/generated/model";
import { useDebounced } from "@/lib/use-debounced";

/** Choose the shop a payment, refund or adjustment is for (search by name, code or mobile). */
export function ShopPicker({ onPick }: { onPick: (shop: RetailerList) => void }) {
  const t = useTranslations("billing.shopPicker");
  const [text, setText] = useState("");
  const search = useDebounced(text.trim(), 250);
  const query = useRetailersList({ search: search || undefined, page_size: 20 });
  const shops = query.data?.data.results ?? [];
  return (
    <section className="space-y-3" aria-labelledby="pick-shop-heading">
      <h2 id="pick-shop-heading" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <div className="relative max-w-md">
        <Search
          aria-hidden
          className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2"
        />
        <Input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("search")}
          aria-label={t("search")}
          className="min-h-11 pl-9"
        />
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : shops.length === 0 ? (
        <EmptyState title={t("none")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {shops.map((shop) => (
            <li key={shop.id}>
              <button
                type="button"
                onClick={() => onPick(shop)}
                className="hover:bg-muted/50 flex min-h-14 w-full flex-col items-start rounded-xl border p-3 text-left"
              >
                <span className="font-medium">{shop.shop_name}</span>
                <span className="text-muted-foreground text-xs">
                  {shop.code} · {shop.owner_name || shop.mobile}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Today's date in India (YYYY-MM-DD), the default for dated forms. */
export function todayInIndia(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}
