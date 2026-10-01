"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { OnOrderLine } from "@/components/planning/product-planning";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/errors";
import {
  backorderAllocationsConfirm,
  backorderAllocationsReject,
  backordersAllocate,
  useBackorderAllocationsList,
  useBackordersList,
  useBackordersRetrieve,
} from "@/lib/api/generated/endpoints/orders/orders";
import type { Allocation, BackorderGroup, WaitingLine } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { toMilli } from "@/lib/qty";

import { refreshOrders } from "./board";
import { OrdersNav } from "./orders-nav";

function Flags({ line }: { line: WaitingLine }) {
  const t = useTranslations("orders.backorders");
  return (
    <span className="flex flex-wrap gap-1.5">
      {line.shop_blocked ? (
        <span className="bg-warning/15 text-warning-strong rounded-full px-2 py-0.5 text-xs">
          {t("shopBlocked")}
        </span>
      ) : null}
      {line.approved_over_limit ? (
        <span className="bg-info/12 text-info-strong rounded-full px-2 py-0.5 text-xs">
          {t("approvedOverLimit")}
        </span>
      ) : line.over_credit_limit ? (
        <span className="bg-warning/15 text-warning-strong rounded-full px-2 py-0.5 text-xs">
          {t("overLimit")}
        </span>
      ) : null}
    </span>
  );
}

/** Proposals waiting for a decision (CONFIRM mode): confirm several at once, or reject one. */
function Proposals({ productId }: { productId?: string }) {
  const t = useTranslations("orders.backorders");
  const { can } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const cursor = useCursor();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = useBackorderAllocationsList({
    status: "PROPOSED",
    product: productId,
    cursor: cursor.cursor,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const allowed = can("orders.allocate_backorder");
  if (!query.isLoading && rows.length === 0) return null;

  const confirm = async (ids: string[]) => {
    try {
      await backorderAllocationsConfirm({ allocations: ids }, idempotent(newIdempotencyKey()));
      toast.success(t("confirmed", { count: ids.length }));
      setSelected(new Set());
    } catch (error) {
      toast.error(message(error));
    }
    refreshOrders(client);
  };

  const columns: DataTableColumn<Allocation>[] = [
    {
      id: "order",
      header: t("order"),
      cell: ({ row }) => (
        <Link
          href={`/manage/orders/${row.original.order}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.order_number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.retailer_name },
    { id: "product", header: t("product"), cell: ({ row }) => row.original.product_name },
    {
      id: "quantity",
      header: t("quantity"),
      cell: ({ row }) => formatQty(row.original.quantity),
    },
    {
      id: "since",
      header: t("since"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    ...(allowed
      ? [
          {
            id: "actions",
            header: t("actions"),
            cell: ({ row }: { row: { original: Allocation } }) => (
              <span className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  className="min-h-10"
                  onClick={() => void confirm([row.original.id])}
                >
                  {t("confirm")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="min-h-10"
                  onClick={async () => {
                    try {
                      await backorderAllocationsReject(row.original.id);
                      toast(t("rejected"));
                    } catch (error) {
                      toast.error(message(error));
                    }
                    refreshOrders(client);
                  }}
                >
                  {t("reject")}
                </Button>
              </span>
            ),
          } satisfies DataTableColumn<Allocation>,
        ]
      : []),
  ];

  return (
    <section className="mb-8 space-y-3" aria-labelledby="proposals-heading">
      <div>
        <h2 id="proposals-heading" className="text-lg font-semibold">
          {t("proposalsTitle")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("proposalsBody")}</p>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["quantity"]}
        pagination={cursor.pagination(page)}
        caption={t("proposalsTitle")}
        empty={{ title: t("noProposals") }}
        cardLayout={{
          order: "title",
          shop: "primary",
          product: "primary",
          quantity: "primary",
          since: "secondary",
          actions: "actions",
        }}
        selection={
          allowed
            ? {
                selected,
                onChange: setSelected,
                actions: (
                  <Button className="min-h-10" onClick={() => void confirm([...selected])}>
                    {t("confirmSelected")}
                  </Button>
                ),
                pageLabel: t("selectPage"),
                rowLabel: (row) => t("selectRow", { number: row.order_number }),
                regionLabel: t("selectionBar"),
              }
            : undefined
        }
      />
    </section>
  );
}

export function BackordersPage() {
  const t = useTranslations("orders.backorders");
  const [search, setSearch] = useState("");
  const query = useBackordersList({ search: search.trim() || undefined });
  const groups = query.data?.data ?? [];
  const columns: DataTableColumn<BackorderGroup>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <Link
          href={`/manage/backorders/${row.original.product_id}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.product_name}
          <span className="text-muted-foreground block text-xs font-normal">
            {row.original.product_code}
          </span>
        </Link>
      ),
    },
    {
      id: "waiting",
      header: t("waiting"),
      cell: ({ row }) => <QtyText value={row.original.waiting} unit={row.original.unit_code} />,
    },
    {
      id: "free",
      header: t("free"),
      cell: ({ row }) => <QtyText value={row.original.available} unit={row.original.unit_code} />,
    },
    { id: "lines", header: t("orders"), cell: ({ row }) => row.original.lines },
    {
      id: "flags",
      header: t("flags"),
      cell: ({ row }) => {
        const g = row.original;
        const parts = [
          g.proposed !== "0.000" ? t("heldForProposals", { qty: formatQty(g.proposed) }) : "",
          g.approved_over_limit ? t("countApproved", { count: g.approved_over_limit }) : "",
          g.skipped_credit ? t("countOverLimit", { count: g.skipped_credit }) : "",
          g.blocked ? t("countBlocked", { count: g.blocked }) : "",
        ].filter(Boolean);
        return <span className="text-muted-foreground text-xs">{parts.join(" · ") || "—"}</span>;
      },
    },
    {
      id: "oldest",
      header: t("oldest"),
      cell: ({ row }) => <DateText value={row.original.oldest_placed_at} />,
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <OrdersNav />
      <Proposals />
      <section className="space-y-3" aria-labelledby="queue-heading">
        <h2 id="queue-heading" className="text-lg font-semibold">
          {t("queueTitle")}
        </h2>
        <DataTable
          columns={columns}
          data={groups}
          getRowId={(row) => row.product_id}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          numericColumns={["waiting", "free", "lines"]}
          caption={t("queueTitle")}
          empty={{ title: t("noneWaiting"), description: t("noneWaitingBody") }}
          cardLayout={{
            product: "title",
            waiting: "primary",
            free: "primary",
            flags: "primary",
            lines: "secondary",
            oldest: "secondary",
          }}
          toolbar={
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("searchPlaceholder")}
              aria-label={t("search")}
              className="min-h-10 max-w-sm"
            />
          }
        />
      </section>
    </>
  );
}

interface OverLimit {
  retailer: string;
  canOverride: boolean;
}

/** One product's waiting orders, oldest first: allocate automatically (FIFO) or by hand. */
export function BackorderProductPage({ productId }: { productId: string }) {
  const t = useTranslations("orders.backorders");
  const { can } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const lines = useBackordersRetrieve(productId);
  const group = useBackordersList().data?.data.find((g) => g.product_id === productId);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [overLimit, setOverLimit] = useState<OverLimit | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const allowed = can("orders.allocate_backorder");
  const rows = lines.data?.data ?? [];
  const chosen = Object.entries(amounts).filter(([, qty]) => (toMilli(qty) ?? 0) > 0);

  const run = async (body: Parameters<typeof backordersAllocate>[0]) => {
    setBusy(true);
    try {
      const response = await backordersAllocate(body, idempotent(newIdempotencyKey()));
      toast.success(t("allocated", { count: response.data.length }));
      setAmounts({});
      setOverLimit(null);
      setReason("");
    } catch (error) {
      if (error instanceof ApiError && error.code === "CREDIT_LIMIT_EXCEEDED") {
        const details = error.details as { retailer?: string; can_override?: boolean };
        setOverLimit({
          retailer: details.retailer ?? "",
          canOverride: Boolean(details.can_override),
        });
      } else {
        toast.error(message(error));
      }
    } finally {
      setBusy(false);
      refreshOrders(client);
    }
  };

  const columns: DataTableColumn<WaitingLine>[] = [
    {
      id: "order",
      header: t("order"),
      cell: ({ row }) => (
        <Link
          href={`/manage/orders/${row.original.order}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.order_number}
        </Link>
      ),
    },
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <span className="space-y-1">
          <span className="block">{row.original.retailer_name}</span>
          <Flags line={row.original} />
        </span>
      ),
    },
    {
      id: "placed",
      header: t("placed"),
      cell: ({ row }) => <DateText value={row.original.placed_at} withTime />,
    },
    {
      id: "waiting",
      header: t("waiting"),
      cell: ({ row }) => formatQty(row.original.qty_backordered),
    },
    ...(allowed
      ? [
          {
            id: "allocate",
            header: t("allocateQty"),
            cell: ({ row }: { row: { original: WaitingLine } }) => (
              <Input
                inputMode="decimal"
                aria-label={t("allocateFor", { number: row.original.order_number })}
                className="min-h-10 w-24 text-right"
                disabled={row.original.shop_blocked}
                value={amounts[row.original.id] ?? ""}
                placeholder="0"
                onChange={(e) =>
                  setAmounts((a) => ({ ...a, [row.original.id]: e.target.value.trim() }))
                }
              />
            ),
          } satisfies DataTableColumn<WaitingLine>,
        ]
      : []),
  ];

  return (
    <>
      <OrdersNav />
      <div className="space-y-6">
        <Button asChild variant="ghost" className="-ml-3 min-h-10">
          <Link href="/manage/backorders">
            <ArrowLeft aria-hidden />
            {t("title")}
          </Link>
        </Button>
        {lines.isLoading ? (
          <CardSkeleton />
        ) : lines.error ? (
          <ErrorState error={lines.error} onRetry={() => void lines.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title={t("nothingWaiting")} />
        ) : (
          <>
            <PageHeader
              title={group?.product_name ?? rows[0]?.product_code ?? ""}
              description={
                group
                  ? t("productSummary", {
                      waiting: formatQty(group.waiting),
                      free: formatQty(group.available),
                      unit: group.unit_code,
                    })
                  : undefined
              }
            />
            <OnOrderLine productId={productId} unit={group?.unit_code} />
            <Proposals productId={productId} />
            <section className="space-y-3" aria-labelledby="waiting-heading">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 id="waiting-heading" className="text-lg font-semibold">
                    {t("waitingTitle")}
                  </h2>
                  <p className="text-muted-foreground text-sm">{t("waitingBody")}</p>
                </div>
                {allowed ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      className="min-h-10"
                      disabled={busy || !group || group.available === "0.000"}
                      onClick={() => void run({ product: productId, auto: true })}
                    >
                      {t("allocateOldest")}
                    </Button>
                    <Button
                      className="min-h-10"
                      disabled={busy || chosen.length === 0}
                      onClick={() =>
                        void run({
                          product: productId,
                          allocations: chosen.map(([line, quantity]) => ({
                            order_line: line,
                            quantity,
                          })),
                        })
                      }
                    >
                      {t("allocateChosen")}
                    </Button>
                  </div>
                ) : null}
              </div>
              {overLimit ? (
                <div role="alert" className="bg-warning/15 space-y-3 rounded-xl p-4 text-sm">
                  <p>
                    {t("overLimitMessage", { shop: overLimit.retailer })}{" "}
                    {overLimit.canOverride ? t("overLimitOverride") : t("overLimitAsk")}
                  </p>
                  {overLimit.canOverride ? (
                    <div className="flex flex-wrap items-end gap-2">
                      <div className="min-w-56 flex-1 space-y-1.5">
                        <Label htmlFor="override-reason">{t("overrideReason")}</Label>
                        <Input
                          id="override-reason"
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          className="min-h-10"
                        />
                      </div>
                      <Button
                        className="min-h-10"
                        disabled={busy || !reason.trim()}
                        onClick={() =>
                          void run({
                            product: productId,
                            allocations: chosen.map(([line, quantity]) => ({
                              order_line: line,
                              quantity,
                            })),
                            override_reason: reason.trim(),
                          })
                        }
                      >
                        {t("allocateAnyway")}
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <DataTable
                columns={columns}
                data={rows}
                getRowId={(row) => row.id}
                numericColumns={["waiting", "allocate"]}
                caption={t("waitingTitle")}
                empty={{ title: t("nothingWaiting") }}
                cardLayout={{
                  order: "title",
                  shop: "primary",
                  waiting: "primary",
                  allocate: "primary",
                  placed: "secondary",
                }}
              />
            </section>
          </>
        )}
      </div>
    </>
  );
}
