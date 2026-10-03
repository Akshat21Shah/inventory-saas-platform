"use client";

import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import type { ReactNode } from "react";

import { DateText, MoneyText } from "@/components/shared/money-text";
import type { UsedFor } from "@/lib/api/generated/model";

/** Where a payment's or credit's money went: bills, old bills or adjustments, and refunds.
 * `action` renders a per-row control (e.g. "Move" for someone who records payments). */
export function UsedForList({
  rows,
  action,
}: {
  rows: UsedFor[];
  action?: (row: UsedFor) => ReactNode;
}) {
  const t = useTranslations("billing.usedFor");
  if (!rows.length) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  return (
    <ul className="divide-y rounded-xl border text-sm">
      {rows.map((row) => {
        const undo = row.amount.startsWith("-");
        return (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <span className="min-w-0">
              {row.target_type === "INVOICE" ? (
                <Link
                  href={`/manage/invoices/${row.target_id}`}
                  className="font-medium hover:underline"
                >
                  {t("invoice", { number: row.target_number })}
                </Link>
              ) : row.target_type === "REFUND" ? (
                <Link
                  href={`/manage/payments/refunds/${row.target_id}`}
                  className="font-medium hover:underline"
                >
                  {t("refund", { number: row.target_number })}
                </Link>
              ) : (
                <span className="font-medium">{row.target_number}</span>
              )}
              <span className="text-muted-foreground block text-xs">
                <DateText value={row.created_at} withTime />
                {" · "}
                {undo ? t("undone") : row.automatic ? t("automatic") : t("byHand")}
                {row.reversed ? ` · ${t("reversed")}` : ""}
              </span>
            </span>
            <span className="flex items-center gap-2">
              <MoneyText value={row.amount} className="font-medium" />
              {!undo && !row.reversed && row.target_type !== "REFUND" && action
                ? action(row)
                : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
