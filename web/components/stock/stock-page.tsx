"use client";

import { ClipboardCheck, Download, FileUp, MoreHorizontal, PackagePlus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filter-bar";
import { QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getStockCountExportUrl } from "@/lib/api/generated/endpoints/imports/imports";
import { useStockList, useStockSummary } from "@/lib/api/generated/endpoints/inventory/inventory";
import type { StockListStatus, StockRow } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";
import { useDebounced } from "@/lib/use-debounced";

import { ProductCell } from "./product-cell";
import { CountCard } from "./shared";

const ALL = "all";
const NO_REORDER = "NO_REORDER_LEVEL";
const STATUSES = ["IN_STOCK", "LOW", "OUT", "BACKORDERED", NO_REORDER] as const;

export function StockPage() {
  const t = useTranslations("stock.overview");
  const { can } = useAuth();
  const errors = useErrorText();
  const params = useSearchParams();
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const initial = params.get("status") ?? ALL;
  const [status, setStatus] = useState<string>(
    (STATUSES as readonly string[]).includes(initial) ? initial : ALL,
  );
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState(ALL);
  const [brand, setBrand] = useState(ALL);
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const summary = useStockSummary();
  const alerts = summary.data?.data.alerts;
  const awaitingCost = summary.data?.data.receipts_awaiting_cost;

  const query = useStockList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    category: category === ALL ? undefined : category,
    brand: brand === ALL ? undefined : brand,
    status: status === ALL || status === NO_REORDER ? undefined : (status as StockListStatus),
    no_reorder_level: status === NO_REORDER ? true : undefined,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];

  function choose(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      cursor.reset();
    };
  }
  const toggleStatus = (value: string) => choose(setStatus)(status === value ? ALL : value);

  async function exportCountSheet() {
    try {
      await downloadFile(getStockCountExportUrl({ file_type: "xlsx" }), "stock-count.xlsx");
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const columns: DataTableColumn<StockRow>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <ProductCell
          id={row.original.id}
          name={row.original.name}
          code={row.original.code}
          thumbnail={row.original.thumbnail_url}
        />
      ),
    },
    {
      id: "available",
      header: t("available"),
      cell: ({ row }) => (
        <QtyText
          value={row.original.available}
          unit={row.original.unit.code}
          className="font-semibold"
        />
      ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    {
      id: "on_hand",
      header: t("onHand"),
      cell: ({ row }) => <QtyText value={row.original.on_hand} />,
    },
    {
      id: "reserved",
      header: t("reserved"),
      cell: ({ row }) => <QtyText value={row.original.reserved} />,
    },
    {
      id: "reorder",
      header: t("reorderLevel"),
      cell: ({ row }) =>
        Number(row.original.reorder_level) > 0 ? (
          <QtyText value={row.original.reorder_level} />
        ) : (
          <span className="text-muted-foreground">{t("notSet")}</span>
        ),
    },
    { id: "category", header: t("category"), cell: ({ row }) => row.original.category || "—" },
  ];

  const filters = [status, category, brand].filter((f) => f !== ALL).length;
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            {can("stock.inward") ? (
              <Button asChild className="min-h-10">
                <Link href="/manage/stock/inwards/new">
                  <PackagePlus aria-hidden />
                  {t("receive")}
                </Link>
              </Button>
            ) : null}
            {can("stock.adjust") ? (
              <>
                <Button asChild variant="outline" className="min-h-10">
                  <Link href="/manage/stock/adjustments/new">
                    <ClipboardCheck aria-hidden />
                    {t("adjust")}
                  </Link>
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      className="min-h-10 max-md:min-w-11"
                      aria-label={t("more")}
                    >
                      <MoreHorizontal aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => void exportCountSheet()}>
                      <Download aria-hidden />
                      {t("exportCount")}
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                      <Link href="/manage/imports/new?kind=OPENING_STOCK">
                        <FileUp aria-hidden />
                        {t("importStock")}
                      </Link>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ) : null}
          </>
        }
      />
      {typeof awaitingCost === "number" && awaitingCost > 0 ? (
        <Link
          href="/manage/stock/inwards?awaiting_cost=true"
          className="border-warning/40 bg-warning/10 mb-4 flex min-h-11 items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
        >
          <span>{t("awaitingCost", { count: awaitingCost })}</span>
          <span className="text-primary shrink-0 font-medium">{t("addCosts")}</span>
        </Link>
      ) : null}
      <div className="mb-4 grid grid-cols-3 gap-3">
        <CountCard
          label={t("lowStock")}
          value={alerts?.LOW_STOCK ?? "—"}
          tone="warning"
          active={status === "LOW"}
          onClick={() => toggleStatus("LOW")}
        />
        <CountCard
          label={t("outOfStock")}
          value={alerts?.OUT_OF_STOCK ?? "—"}
          tone="danger"
          active={status === "OUT"}
          onClick={() => toggleStatus("OUT")}
        />
        <CountCard
          label={t("shopsWaiting")}
          value={alerts?.BACKORDER_DEMAND ?? "—"}
          tone="info"
          active={status === "BACKORDERED"}
          onClick={() => toggleStatus("BACKORDERED")}
        />
      </div>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["available", "on_hand", "reserved", "reorder"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          debounced || filters
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={{
          product: "title",
          available: "primary",
          status: "primary",
          on_hand: "secondary",
          reserved: "secondary",
          reorder: "secondary",
          category: "secondary",
        }}
        toolbar={
          <FilterBar
            active={filters}
            onClear={() => {
              for (const reset of [setStatus, setCategory, setBrand]) reset(ALL);
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
                className="h-10 w-full sm:w-64"
              />
            }
            filters={
              <>
                <FilterSelect
                  label={t("status")}
                  value={status}
                  onChange={choose(setStatus)}
                  options={[
                    { value: ALL, label: t("anyStatus") },
                    ...STATUSES.map((value) => ({ value, label: t(`statuses.${value}`) })),
                  ]}
                />
                <FilterSelect
                  label={t("category")}
                  value={category}
                  onChange={choose(setCategory)}
                  options={[{ value: ALL, label: t("allCategories") }, ...categories]}
                />
                <FilterSelect
                  label={t("brand")}
                  value={brand}
                  onChange={choose(setBrand)}
                  options={[{ value: ALL, label: t("allBrands") }, ...brands]}
                />
              </>
            }
          />
        }
      />
    </>
  );
}
