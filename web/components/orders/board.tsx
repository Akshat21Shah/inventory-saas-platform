"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Volume2, VolumeX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { OrderStatus } from "@/components/shared/order-status";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ordersAccept,
  useOrdersCounts,
  useOrdersList,
} from "@/lib/api/generated/endpoints/orders/orders";
import {
  OrderStatusEnum,
  type OrderRow,
  type OrdersListStatus,
  type OrdersListTab,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { useListSearch } from "@/lib/list-search";

import { OrdersNav } from "./orders-nav";
import { useOrderSound } from "./sound";

const TABS: OrdersListTab[] = ["new", "on_hold", "backorders", "in_progress", "completed"];
const ALL = "all";

export function refreshOrders(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({
    predicate: (q) => {
      const key = String(q.queryKey[0] ?? "");
      return (
        key.startsWith("/api/v1/orders") ||
        key.startsWith("/api/v1/fulfilments") ||
        key.startsWith("/api/v1/backorders")
      );
    },
  });
}

/** The distributor's order board (PLAN §3.8): what needs action first. */
export function OrdersBoard() {
  const t = useTranslations("orders.board");
  const statuses = useTranslations("orderStatus");
  const { can } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const sound = useOrderSound();
  const [tab, setTab] = useState<OrdersListTab>("new");
  const [search, setSearch] = useListSearch();
  const [status, setStatus] = useState<string>(ALL);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const cursor = useCursor();
  const term = useDebounced(search.trim(), 300);
  const counts = useOrdersCounts({ query: { refetchInterval: 60_000 } }).data?.data;
  const query = useOrdersList({
    tab,
    cursor: cursor.cursor,
    search: term || undefined,
    status: status === ALL ? undefined : (status as OrdersListStatus),
    placed_from: from || undefined,
    placed_to: to || undefined,
  });
  const page = query.data?.data;
  const canAccept = tab === "new" && can("orders.manage");

  const acceptSelected = async () => {
    const ids = [...selected];
    const results = await Promise.allSettled(
      ids.map((id) => ordersAccept(id, idempotent(newIdempotencyKey()))),
    );
    const failed = results.filter((r) => r.status === "rejected");
    const done = ids.length - failed.length;
    if (done) toast.success(t("accepted", { count: done }));
    if (failed[0]?.status === "rejected") toast.error(message(failed[0].reason));
    setSelected(new Set());
    refreshOrders(client);
  };

  const columns: DataTableColumn<OrderRow>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/orders/${row.original.id}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <span className="space-y-0.5">
          <span className="block">{row.original.retailer_name}</span>
          {row.original.placed_by_label ? (
            <span className="text-muted-foreground block text-xs">
              {t("placedBy", { name: row.original.placed_by_label })}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <OrderStatus status={row.original.status} itemsToFollow={row.original.items_to_follow} />
          {row.original.backorder_state === "OPEN" ? (
            <span className="text-info-strong text-xs">{t("itemsWaiting")}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "items",
      header: t("items"),
      cell: ({ row }) => row.original.line_count,
    },
    {
      id: "total",
      header: t("total"),
      cell: ({ row }) => <MoneyText value={row.original.grand_total} />,
    },
    {
      id: "placed",
      header: t("placed"),
      cell: ({ row }) => <DateText value={row.original.placed_at} withTime />,
    },
  ];

  const active = [term, status !== ALL, from, to].filter(Boolean).length;

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="min-h-10 gap-2"
              aria-pressed={sound.on}
              onClick={sound.toggle}
            >
              {sound.on ? <Volume2 aria-hidden /> : <VolumeX aria-hidden />}
              {sound.on ? t("soundOn") : t("soundOff")}
            </Button>
            {can("orders.create_on_behalf") ? (
              <Button asChild className="min-h-10 gap-2">
                <Link href="/manage/orders/new">
                  <Plus aria-hidden />
                  {t("newOrder")}
                </Link>
              </Button>
            ) : null}
          </div>
        }
      />
      <OrdersNav />
      <div
        role="tablist"
        aria-label={t("tabs")}
        className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0"
      >
        {TABS.map((value) => {
          const count = value === "completed" ? undefined : counts?.[value];
          return (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={tab === value}
              onClick={() => {
                setTab(value);
                setSelected(new Set());
                cursor.reset();
              }}
              className={cn(
                "flex min-h-11 shrink-0 items-center gap-2 rounded-full border px-4 text-sm md:min-h-10",
                tab === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
              )}
            >
              {t(`tab.${value}`)}
              {count ? (
                <span className="bg-primary text-primary-foreground rounded-full px-2 text-xs tabular-nums">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["items", "total"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t(`empty.${tab}`), description: t("emptyBody") }}
        cardLayout={{
          number: "title",
          shop: "primary",
          status: "primary",
          total: "primary",
          placed: "secondary",
          items: "secondary",
        }}
        selection={
          canAccept
            ? {
                selected,
                onChange: setSelected,
                actions: (
                  <Button className="min-h-10" onClick={() => void acceptSelected()}>
                    {t("acceptSelected")}
                  </Button>
                ),
                pageLabel: t("selectPage"),
                rowLabel: (row) => t("selectRow", { number: row.number }),
                regionLabel: t("selectionBar"),
              }
            : undefined
        }
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              setSearch("");
              setStatus(ALL);
              setFrom("");
              setTo("");
              cursor.reset();
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  cursor.reset();
                }}
                placeholder={t("searchPlaceholder")}
                aria-label={t("search")}
                className="min-h-10"
              />
            }
            filters={
              <>
                <FilterSelect
                  label={t("status")}
                  value={status}
                  onChange={(value) => {
                    setStatus(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allStatuses") },
                    ...Object.values(OrderStatusEnum).map((value) => ({
                      value,
                      label: statuses(value),
                    })),
                  ]}
                />
                <label className="flex flex-col gap-1 text-xs">
                  {t("from")}
                  <Input
                    type="date"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                    className="min-h-10"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  {t("to")}
                  <Input
                    type="date"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    className="min-h-10"
                  />
                </label>
              </>
            }
          />
        }
      />
    </>
  );
}
