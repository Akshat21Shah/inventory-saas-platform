"use client";

import { useTranslations } from "next-intl";

import { DateText } from "./money-text";
import { StatusBadge } from "./status-badge";

export interface TimelineEntry {
  id: string;
  created_at: string;
  event: string;
  to_status: string;
  note: string;
  payload: unknown;
  /** Staff only: who did it. */
  by?: string;
}

function detail(entry: TimelineEntry): Record<string, unknown> {
  return entry.payload && typeof entry.payload === "object"
    ? (entry.payload as Record<string, unknown>)
    : {};
}

/** What happened to an order, newest first, in plain words. The status after each step is the
 * order's (e.g. "Partly delivered, 1 item to follow", ADR-045). */
export function OrderTimeline({ entries }: { entries: readonly TimelineEntry[] }) {
  const t = useTranslations("orderEvents");
  const s = useTranslations("orderStatus");
  const newestFirst = [...entries].reverse();
  return (
    <ol className="space-y-4 border-l pl-4" aria-label={t("title")}>
      {newestFirst.map((entry) => {
        const data = detail(entry);
        const toFollow = typeof data.items_to_follow === "number" ? data.items_to_follow : 0;
        const shipment = typeof data.shipment === "string" ? data.shipment : "";
        return (
          <li key={entry.id} className="relative space-y-1">
            <span
              aria-hidden
              className="bg-primary absolute top-1.5 -left-[21px] size-2.5 rounded-full"
            />
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
              {t.has(entry.event) ? t(entry.event) : entry.event}
              {shipment ? (
                <span className="text-muted-foreground font-normal">{shipment}</span>
              ) : null}
              <StatusBadge status={entry.to_status} labels="orderStatus" />
              {entry.to_status === "PARTLY_DELIVERED" && toFollow ? (
                <span className="text-muted-foreground text-xs font-normal">
                  {s("toFollow", { count: toFollow })}
                </span>
              ) : null}
            </p>
            <p className="text-muted-foreground text-xs">
              <DateText value={entry.created_at} withTime />
              {entry.by ? ` · ${entry.by}` : ""}
            </p>
            {entry.note ? <p className="text-sm">{entry.note}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}
