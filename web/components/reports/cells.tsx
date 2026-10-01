import Link from "next/link";

import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import type { Column } from "@/lib/api/generated/model";

export type ReportRow = Record<string, unknown>;

/** Where a row leads, from the link ids the server adds (`engine.LINKS`), most specific first. */
const LINKS: [string, (id: string) => string][] = [
  ["invoice_id", (id) => `/manage/invoices/${id}`],
  ["credit_note_id", (id) => `/manage/invoices/credit-notes/${id}`],
  ["order_id", (id) => `/manage/orders/${id}`],
  ["payment_id", (id) => `/manage/payments/${id}`],
  ["product_id", (id) => `/manage/products/${id}`],
  ["retailer_id", (id) => `/manage/retailers/${id}`],
];

export function rowHref(row: ReportRow): string | null {
  for (const [key, href] of LINKS) {
    const id = row[key];
    if (typeof id === "string" && id) return href(id);
  }
  return null;
}

export const NUMERIC_KINDS = new Set(["money", "qty", "int", "percent"]);

/** A value as its kind reads: money in rupees, quantities, DD-MM-YYYY dates, percentages. */
export function ReportValue({ column, value }: { column: Column; value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  const text = String(value);
  switch (column.kind) {
    case "money":
      return <MoneyText value={text} />;
    case "qty":
      return <QtyText value={text} />;
    case "date":
      return <DateText value={text} />;
    case "percent":
      return <span className="tabular-nums">{text}%</span>;
    case "int":
      return <span className="tabular-nums">{text}</span>;
    default:
      return <>{text}</>;
  }
}

/** The row's heading cell: a link to what the row is about, when the server gave one. */
export function ReportLinkCell({ column, row }: { column: Column; row: ReportRow }) {
  const href = rowHref(row);
  const value = <ReportValue column={column} value={row[column.key]} />;
  return href ? (
    <Link href={href} className="text-primary font-medium underline-offset-4 hover:underline">
      {value}
    </Link>
  ) : (
    <span className="font-medium">{value}</span>
  );
}
