"use client";

import { useTranslations } from "@/lib/i18n/translations";

import type { DemandRate } from "@/lib/api/generated/model";
import { formatQty } from "@/lib/format";

/** "about 2 PCS a month": the server's rate (per day from 1 a day, else per week or month). */
export function useDemandRate() {
  const t = useTranslations("planning.rate");
  return (rate: DemandRate, unit: string) =>
    Number(rate.quantity) === 0
      ? t("lessThanOne", { unit })
      : t("about", { qty: formatQty(rate.quantity, 2), unit, period: rate.period });
}

/** How long the stock lasts, in whole days rounded down by the server: "Out of stock", "Less than
 * a day", "About 12 days"; null when nothing was ordered lately. */
export function useStockLasts() {
  const t = useTranslations("planning.stock");
  return (available: string, days: string | null) => {
    if (Number(available) <= 0) return t("out");
    if (days === null) return null;
    return Number(days) < 1 ? t("lessThanDay") : t("days", { count: Number(days) });
  };
}
