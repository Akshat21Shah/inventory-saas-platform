"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { StatusBadge } from "./status-badge";

/** An order's status for shops and staff alike; "Partly delivered" says how many products are
 * still to follow (ADR-045). */
export function OrderStatus({
  status,
  itemsToFollow,
  className,
}: {
  status: string;
  itemsToFollow?: number;
  className?: string;
}) {
  const t = useTranslations("orderStatus");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      <StatusBadge status={status} labels="orderStatus" />
      {status === "PARTLY_DELIVERED" && itemsToFollow ? (
        <span className="text-muted-foreground text-xs">
          {t("toFollow", { count: itemsToFollow })}
        </span>
      ) : null}
    </span>
  );
}
