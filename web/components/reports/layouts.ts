import type { CardSlot } from "@/components/shared/data-table";
import type { Column } from "@/lib/api/generated/model";

/**
 * Per report: the column that heads a row (a link to what the row is about, and the card's title
 * on phones and tablets) and the 3-4 lines a card always shows (CLAUDE.md §6a). The other columns
 * are behind "More". Columns the user may not see (costs) are simply absent.
 */
const LAYOUTS: Record<string, { title: string; primary: string[] }> = {
  sales_summary: { title: "period", primary: ["total", "invoices", "credited"] },
  sales_by_product: { title: "name", primary: ["qty", "total", "margin"] },
  sales_by_category: { title: "name", primary: ["total", "share", "margin"] },
  sales_by_brand: { title: "name", primary: ["total", "share", "margin"] },
  sales_by_shop: { title: "name", primary: ["total", "invoices", "last_invoice"] },
  sales_by_salesperson: { title: "name", primary: ["total", "shops", "share"] },
  sales_by_invoice: { title: "doc_number", primary: ["shop_name", "day", "total"] },
  margin_own_vs_traded: { title: "name", primary: ["taxable", "margin", "margin_pct"] },
  stock_summary: { title: "name", primary: ["available", "status", "value"] },
  stock_valuation: { title: "name", primary: ["on_hand", "value"] },
  low_stock: { title: "name", primary: ["available", "reorder_level", "shortfall"] },
  stock_movements: { title: "name", primary: ["when", "type", "delta_on_hand", "on_hand_after"] },
  stock_movement_class: { title: "name", primary: ["class", "sales_value", "on_hand"] },
  backorder_demand: { title: "name", primary: ["qty", "shops", "oldest", "value"] },
  fulfilment_rate: { title: "period", primary: ["orders", "in_full_pct", "delivered_pct"] },
  receivables_ageing: { title: "name", primary: ["owed", "net", "oldest_due"] },
  collections: { title: "shop", primary: ["amount", "payment_date", "mode", "status"] },
  shop_activity: { title: "name", primary: ["segment", "last_order", "days_since"] },
  salesperson_collections: { title: "name", primary: ["total", "with_salesman", "oldest_pending"] },
  gst_summary: { title: "section", primary: ["documents", "taxable", "tax"] },
};

/** The heading column and the card slots for a report's columns (a report without a layout:
 * the first column heads, the first three columns with a total are always shown). */
export function layoutFor(
  code: string,
  columns: Column[],
): { heading: string | undefined; slots: Partial<Record<string, CardSlot>> } {
  const keys = new Set(columns.map((c) => c.key));
  const own = LAYOUTS[code];
  const heading = own && keys.has(own.title) ? own.title : columns[0]?.key;
  const primary = new Set(
    own
      ? own.primary
      : columns
          .filter((c) => c.total)
          .map((c) => c.key)
          .slice(0, 3),
  );
  const slots: Partial<Record<string, CardSlot>> = {};
  for (const c of columns) {
    slots[c.key] = c.key === heading ? "title" : primary.has(c.key) ? "primary" : "secondary";
  }
  return { heading, slots };
}
