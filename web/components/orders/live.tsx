"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { useLiveUpdates } from "@/lib/live";

import { refreshOrders } from "./board";
import { playChime } from "./sound";

/** Order and backorder events for staff who may view orders: every screen refreshes; a new
 * order (or one waiting for credit approval, or stock arriving for backorders) pops up with a
 * chime when sound is on. */
export function DistributorLiveUpdates() {
  const t = useTranslations("orders.live");
  const client = useQueryClient();
  const router = useRouter();
  const { me, can } = useAuth();
  useLiveUpdates({
    enabled: Boolean(me?.tenant) && can("orders.view"),
    onEvent: (event) => {
      refreshOrders(client);
      const open = event.order
        ? { label: t("open"), onClick: () => router.push(`/manage/orders/${event.order}`) }
        : undefined;
      if (event.event === "order.placed" || event.event === "order.on_hold") {
        playChime();
        toast(
          t(event.event === "order.placed" ? "placed" : "onHold", {
            number: event.number ?? "",
            shop: event.retailer_name ?? "",
          }),
          { action: open, duration: 10_000 },
        );
      } else if (event.event === "backorder.proposed") {
        toast(t("proposed", { number: event.number ?? "" }), {
          action: { label: t("review"), onClick: () => router.push("/manage/backorders") },
        });
      } else if (event.event === "order.cancelled" && event.status === "CANCELLED") {
        toast(t("cancelled", { number: event.number ?? "" }), { action: open });
      }
    },
    onReconnect: () => refreshOrders(client),
  });
  return null;
}
