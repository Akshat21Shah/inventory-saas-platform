"use client";

import { useState } from "react";

import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { useStockAlertsList } from "@/lib/api/generated/endpoints/inventory/inventory";
import type { Alert, StockAlertsListStatus, StockAlertsListType } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

import { ProductCell } from "./product-cell";

const ALL = "all";
const TYPES: StockAlertsListType[] = ["LOW_STOCK", "OUT_OF_STOCK", "BACKORDER_DEMAND"];

export function AlertsPage() {
  const t = useTranslations("stock.alerts");
  const types = useTranslations("stock.alertTypes");
  const [status, setStatus] = useState<StockAlertsListStatus>("OPEN");
  const [type, setType] = useState<string>(ALL);
  const cursor = useCursor();
  const query = useStockAlertsList({
    cursor: cursor.cursor,
    status,
    type: type === ALL ? undefined : (type as StockAlertsListType),
  });
  const page = query.data?.data;
  const resolved = status === "RESOLVED";

  const columns: DataTableColumn<Alert>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <ProductCell
          id={row.original.product.id}
          name={row.original.product.name}
          code={row.original.product.code}
        />
      ),
    },
    {
      id: "type",
      header: t("type"),
      cell: ({ row }) => (
        <span
          className={cn(
            "font-medium",
            row.original.alert_type === "OUT_OF_STOCK" && "text-destructive",
            row.original.alert_type === "LOW_STOCK" && "text-warning-strong",
            row.original.alert_type === "BACKORDER_DEMAND" && "text-info-strong",
          )}
        >
          {types(row.original.alert_type)}
        </span>
      ),
    },
    {
      id: "value",
      header: t("atTheTime"),
      cell: ({ row }) => (
        <QtyText value={row.original.value_at_open} unit={row.original.product.unit.code} />
      ),
    },
    {
      id: "since",
      header: resolved ? t("opened") : t("since"),
      cell: ({ row }) => <DateText value={row.original.opened_at} withTime />,
    },
    ...(resolved
      ? [
          {
            id: "resolved",
            header: t("resolved"),
            cell: ({ row }: { row: { original: Alert } }) =>
              row.original.resolved_at ? (
                <DateText value={row.original.resolved_at} withTime />
              ) : (
                "—"
              ),
          } satisfies DataTableColumn<Alert>,
        ]
      : []),
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div role="tablist" aria-label={t("show")} className="mb-4 flex gap-2">
        {(["OPEN", "RESOLVED"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={status === value}
            onClick={() => {
              setStatus(value);
              cursor.reset();
            }}
            className={cn(
              "min-h-11 rounded-full border px-4 text-sm md:min-h-10",
              status === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
            )}
          >
            {t(value === "OPEN" ? "open" : "resolvedTab")}
          </button>
        ))}
      </div>
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["value"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          resolved
            ? { title: t("noneResolved") }
            : { title: t("noneOpen"), description: t("noneOpenBody") }
        }
        cardLayout={{
          product: "title",
          type: "primary",
          value: "primary",
          since: "secondary",
          resolved: "secondary",
        }}
        toolbar={
          <FilterBar
            active={type === ALL ? 0 : 1}
            onClear={() => setType(ALL)}
            filters={
              <FilterSelect
                label={t("type")}
                value={type}
                onChange={(value) => {
                  setType(value);
                  cursor.reset();
                }}
                options={[
                  { value: ALL, label: t("allTypes") },
                  ...TYPES.map((value) => ({ value, label: types(value) })),
                ]}
              />
            }
          />
        }
      />
    </>
  );
}
