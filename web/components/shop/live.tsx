"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { refreshNotifications } from "@/components/notifications/scope";
import { useLiveUpdates } from "@/lib/live";

/** Events the shop is told about in a short note (the order screens refresh for all of them). */
const TOLD = new Set([
  "order.accepted",
  "order.rejected",
  "order.cancelled",
  "order.modified",
  "order.hold_approved",
  "order.dispatched",
  "order.delivered",
  "order.completed",
  "order.short_supplied",
  "backorder.allocated",
  "backorder.cancelled",
]);

function refreshShopOrders(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({
    predicate: (q) => {
      const key = String(q.queryKey[0] ?? "");
      return key.startsWith("/api/v1/shop/orders") || key.startsWith("/api/v1/shop/home");
    },
  });
}

/** Order changes pushed to this shop: screens refresh, and a short note says what happened. */
export function ShopLiveUpdates() {
  const t = useTranslations("shop.live");
  const client = useQueryClient();
  const { me } = useAuth();
  useLiveUpdates({
    enabled: Boolean(me?.retailer),
    onNotification: () => refreshNotifications(client),
    onEvent: (event) => {
      refreshShopOrders(client);
      if (TOLD.has(event.event) && event.number) {
        toast(t(event.event.replace(".", "_"), { number: event.number }));
      }
    },
    onReconnect: () => {
      refreshShopOrders(client);
      refreshNotifications(client);
    },
  });
  return null;
}
