"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { FilterSelect } from "@/components/catalog/controls";
import { Input } from "@/components/ui/input";
import { useStockMovementsList } from "@/lib/api/generated/endpoints/inventory/inventory";
import type { Movement, MovementTypeEnum } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { cn } from "@/lib/utils";

import { ProductCell } from "./product-cell";

const ALL = "all";
export const MOVEMENT_TYPES: MovementTypeEnum[] = [
  "INWARD",
  "ADJUSTMENT_IN",
  "ADJUSTMENT_OUT",
  "DAMAGE",
  "SALE",
  "RETURN",
  "RESERVE",
  "RELEASE",
  "TRANSFER_IN",
  "TRANSFER_OUT",
];

/** Where a movement came from: its goods receipt or adjustment, when it has a page. */
export function referenceHref(movement: Movement): string | null {
  if (movement.reference_type === "INWARD") return `/manage/stock/inwards/${movement.reference_id}`;
  if (movement.reference_type === "ADJUSTMENT") {
    return `/manage/stock/adjustments/${movement.reference_id}`;
  }
  return null;
}

/** "+12" / "−3" for the change to stock on hand (reservations change "reserved" instead). */
function Change({ movement }: { movement: Movement }) {
  const onHand = Number(movement.delta_on_hand);
  const delta = onHand !== 0 ? movement.delta_on_hand : movement.delta_reserved;
  const sign = Number(delta) > 0 ? "+" : "−";
  return (
    <span
      className={cn(
        "font-medium tabular-nums",
        onHand > 0 && "text-success-strong",
        onHand < 0 && "text-destructive",
      )}
    >
      {sign}
      <QtyText value={delta.replace("-", "")} unit={movement.product.unit.code} />
    </span>
  );
}

export function MovementsTable({
  productId,
  withProduct = true,
  filters,
  emptyText,
}: {
  productId?: string;
  withProduct?: boolean;
  filters?: { type?: MovementTypeEnum; from?: string; to?: string };
  emptyText?: string;
}) {
  const t = useTranslations("stock.movements");
  const types = useTranslations("stock.movementTypes");
  const cursor = useCursor();
  const query = useStockMovementsList({
    cursor: cursor.cursor,
    product: productId,
    type: filters?.type,
    from: filters?.from || undefined,
    to: filters?.to || undefined,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const showValue = rows.some((row) => row.value !== null);

  const columns: DataTableColumn<Movement>[] = [
    {
      id: "when",
      header: t("when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    ...(withProduct
      ? [
          {
            id: "product",
            header: t("product"),
            cell: ({ row }: { row: { original: Movement } }) => (
              <ProductCell
                id={row.original.product.id}
                name={row.original.product.name}
                code={row.original.product.code}
              />
            ),
          } satisfies DataTableColumn<Movement>,
        ]
      : []),
    {
      id: "type",
      header: t("type"),
      cell: ({ row }) => types(row.original.movement_type),
    },
    { id: "change", header: t("change"), cell: ({ row }) => <Change movement={row.original} /> },
    {
      id: "after",
      header: t("onHandAfter"),
      cell: ({ row }) => (
        <QtyText value={row.original.on_hand_after} unit={row.original.product.unit.code} />
      ),
    },
    {
      id: "reference",
      header: t("reference"),
      cell: ({ row }) => {
        const href = referenceHref(row.original);
        const label = row.original.reference_number || "—";
        return href ? (
          <Link href={href} className="text-primary font-medium hover:underline">
            {label}
          </Link>
        ) : (
          label
        );
      },
    },
    {
      id: "reason",
      header: t("reason"),
      cell: ({ row }) => row.original.reason || "—",
    },
    { id: "by", header: t("by"), cell: ({ row }) => row.original.by || "—" },
    ...(showValue
      ? [
          {
            id: "value",
            header: t("value"),
            cell: ({ row }: { row: { original: Movement } }) =>
              row.original.value ? <MoneyText value={row.original.value} /> : "—",
          } satisfies DataTableColumn<Movement>,
        ]
      : []),
  ];

  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      numericColumns={["change", "after", "value"]}
      pagination={cursor.pagination(page)}
      caption={t("title")}
      empty={{ title: emptyText ?? t("emptyTitle"), description: t("emptyBody") }}
      cardLayout={{
        [withProduct ? "product" : "type"]: "title",
        type: withProduct ? "primary" : "title",
        change: "primary",
        after: "primary",
        when: "secondary",
        reference: "secondary",
        reason: "secondary",
        by: "secondary",
        value: "secondary",
      }}
    />
  );
}

export function MovementsPage() {
  const t = useTranslations("stock.movements");
  const types = useTranslations("stock.movementTypes");
  const [type, setType] = useState<string>(ALL);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const active = [type !== ALL, Boolean(from), Boolean(to)].filter(Boolean).length;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <FilterBar
        active={active}
        onClear={() => {
          setType(ALL);
          setFrom("");
          setTo("");
        }}
        filters={
          <>
            <FilterSelect
              label={t("type")}
              value={type}
              onChange={setType}
              options={[
                { value: ALL, label: t("allTypes") },
                ...MOVEMENT_TYPES.map((value) => ({ value, label: types(value) })),
              ]}
            />
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground w-10 sm:w-auto">{t("from")}</span>
              <Input
                type="date"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="h-10 w-full sm:w-40"
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground w-10 sm:w-auto">{t("to")}</span>
              <Input
                type="date"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="h-10 w-full sm:w-40"
              />
            </label>
          </>
        }
      />
      <div className="mt-4">
        <MovementsTable
          filters={{ type: type === ALL ? undefined : (type as MovementTypeEnum), from, to }}
        />
      </div>
    </>
  );
}
