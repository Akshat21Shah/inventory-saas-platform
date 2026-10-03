"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { useFulfilmentsList } from "@/lib/api/generated/endpoints/orders/orders";
import type { FulfilmentRow, FulfilmentsListStatus } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

import { OrdersNav } from "./orders-nav";

const STAGES: FulfilmentsListStatus[] = ["ALLOCATED", "PACKED", "DISPATCHED", "DELIVERED"];

/** The warehouse's queue: shipments to pack, to dispatch, on the way. */
export function ShipmentsPage() {
  const t = useTranslations("orders.shipments");
  const [status, setStatus] = useState<FulfilmentsListStatus>("ALLOCATED");
  const cursor = useCursor();
  const query = useFulfilmentsList({ status, cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<FulfilmentRow>[] = [
    {
      id: "number",
      header: t("shipment"),
      cell: ({ row }) => (
        <Link
          href={`/manage/orders/${row.original.order}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.retailer_name },
    {
      id: "kind",
      header: t("kind"),
      cell: ({ row }) => t(row.original.kind === "BACKORDER" ? "backorder" : "first"),
    },
    { id: "items", header: t("items"), cell: ({ row }) => row.original.line_count },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} labels="shipmentStatus" />,
    },
    {
      id: "since",
      header: t("since"),
      cell: ({ row }) => (
        <DateText
          value={row.original.dispatched_at ?? row.original.packed_at ?? row.original.created_at}
          withTime
        />
      ),
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <OrdersNav />
      <div
        role="tablist"
        aria-label={t("show")}
        className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0"
      >
        {STAGES.map((value) => (
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
              "min-h-11 shrink-0 rounded-full border px-4 text-sm md:min-h-10",
              status === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
            )}
          >
            {t(`stage.${value}`)}
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
        numericColumns={["items"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t(`empty.${status}`) }}
        cardLayout={{
          number: "title",
          shop: "primary",
          status: "primary",
          items: "primary",
          kind: "secondary",
          since: "secondary",
        }}
      />
    </>
  );
}
