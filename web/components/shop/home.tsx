"use client";

import { useMutation } from "@tanstack/react-query";
import { ChevronRight, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { OrderStatus } from "@/components/shared/order-status";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { OwedCard } from "@/components/shop/account";
import {
  getShopCartRetrieveQueryKey,
  shopOrderRepeat,
  useShopCategories,
  useShopHome,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopOrderRow } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { useQueryClient } from "@tanstack/react-query";

import { CategoryTiles, OnHoldNotice, ProductCard, SearchBox } from "./catalog";

export function OrderRowLink({ order }: { order: ShopOrderRow }) {
  const t = useTranslations("shop.orders");
  return (
    <li>
      <Link
        href={`/shop/orders/${order.id}`}
        className="hover:bg-muted/50 flex min-h-16 items-center gap-3 rounded-xl border p-3"
      >
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium">{order.number}</span>
            <OrderStatus status={order.status} itemsToFollow={order.items_to_follow} />
          </span>
          <span className="text-muted-foreground block text-xs">
            <DateText value={order.placed_at} /> · {t("items", { count: order.line_count })}
            {order.placed_by_label ? ` · ${t("placedBy", { name: order.placed_by_label })}` : ""}
          </span>
        </span>
        <MoneyText value={order.grand_total} className="font-semibold" />
        <ChevronRight aria-hidden className="text-muted-foreground size-4 shrink-0" />
      </Link>
    </li>
  );
}

function RepeatLastOrder() {
  const t = useTranslations("shop.home");
  const home = useShopHome();
  const router = useRouter();
  const client = useQueryClient();
  const { message } = useErrorText();
  const last = home.data?.data.last_order;
  const repeat = useMutation({
    mutationFn: (orderId: string) => shopOrderRepeat(orderId),
    onSuccess: (response) => {
      client.setQueryData(getShopCartRetrieveQueryKey(), { ...response, data: response.data.cart });
      const skipped = response.data.skipped;
      if (skipped.length) {
        toast(
          t("skipped", { count: skipped.length, names: skipped.map((s) => s.name).join(", ") }),
        );
      }
      router.push("/shop/cart");
    },
    onError: (error) => toast.error(message(error)),
  });
  if (home.isLoading) return <CardSkeleton />;
  if (home.error) return <ErrorState error={home.error} onRetry={() => void home.refetch()} />;
  if (!last || last.items.length === 0) return null;
  return (
    <section className="space-y-3" aria-labelledby="repeat-heading">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="repeat-heading" className="text-lg font-semibold">
            {t("repeatTitle")}
          </h2>
          <p className="text-muted-foreground text-xs">
            {t("repeatFrom", { number: last.number })} · <DateText value={last.placed_at} />
          </p>
        </div>
        <Button
          variant="outline"
          className="min-h-11 gap-2"
          disabled={repeat.isPending}
          onClick={() => repeat.mutate(last.id)}
        >
          <RotateCcw aria-hidden className="size-4" />
          {t("repeatAll")}
        </Button>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {last.items.map((item) => (
          <ProductCard key={item.id} product={item} lastQuantity={item.last_quantity} />
        ))}
      </ul>
    </section>
  );
}

function RecentOrders() {
  const t = useTranslations("shop.home");
  const home = useShopHome();
  const data = home.data?.data;
  if (home.isLoading || home.error || !data) return null;
  if (data.recent_orders.length === 0) {
    return <EmptyState title={t("noOrdersTitle")} description={t("noOrdersBody")} />;
  }
  return (
    <section className="space-y-3" aria-labelledby="recent-heading">
      <div className="flex items-center justify-between">
        <h2 id="recent-heading" className="text-lg font-semibold">
          {t("recentTitle")}
        </h2>
        <Link
          href="/shop/orders"
          className="text-brand-700 inline-flex min-h-11 items-center text-sm font-medium hover:underline"
        >
          {t("allOrders")}
        </Link>
      </div>
      {data.open_orders || data.waiting_items ? (
        <p className="text-muted-foreground text-sm">
          {t("summary", { open: data.open_orders, waiting: data.waiting_items })}
        </p>
      ) : null}
      <ul className="space-y-2">
        {data.recent_orders.map((order) => (
          <OrderRowLink key={order.id} order={order} />
        ))}
      </ul>
    </section>
  );
}

export function ShopHome() {
  const t = useTranslations("shop");
  const { me } = useAuth();
  const categories = useShopCategories();
  const tree = categories.data?.data ?? [];
  return (
    <div className="space-y-7">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">
          {me?.retailer ? t("hello", { shop: me.retailer.shop_name }) : t("catalogTitle")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("homeBody")}</p>
      </div>
      <OnHoldNotice />
      <OwedCard />
      <SearchBox />
      <RepeatLastOrder />
      <RecentOrders />
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t("categories")}</h2>
          <Link
            href="/shop/catalog"
            className="text-brand-700 inline-flex min-h-11 items-center text-sm font-medium hover:underline"
          >
            {t("allProducts")}
          </Link>
        </div>
        {categories.isLoading ? (
          <CardSkeleton />
        ) : categories.error ? (
          <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
        ) : tree.length ? (
          <CategoryTiles categories={tree} />
        ) : (
          <Button asChild variant="outline" className="min-h-11 w-full">
            <Link href="/shop/catalog">{t("allProducts")}</Link>
          </Button>
        )}
      </section>
    </div>
  );
}
