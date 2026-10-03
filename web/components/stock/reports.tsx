"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getReportsLowStockExportUrl,
  getReportsStockValuationExportUrl,
  useReportsLowStock,
  useReportsLowStockSummary,
  useReportsStockValuation,
  useReportsStockValuationProducts,
} from "@/lib/api/generated/endpoints/reports/reports";
import type { Bucket, LowStockRow, ValuationRow } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { cn } from "@/lib/utils";

import { ProductCell } from "./product-cell";
import { CountCard } from "./shared";

const ALL = "all";

/** Mirrors the server (ADR-042): costs, and the stock or the financial reports. Cosmetic only. */
export function canSeeValuation(can: (code: string) => boolean): boolean {
  return can("costs.view") && (can("reports.stock") || can("reports.financial"));
}

function useReportFilters() {
  const t = useTranslations("stock.reports");
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const [category, setCategory] = useState(ALL);
  const [brand, setBrand] = useState(ALL);
  const params = {
    category: category === ALL ? undefined : category,
    brand: brand === ALL ? undefined : brand,
  };
  const bar = (onChange: () => void) => (
    <FilterBar
      active={[category, brand].filter((f) => f !== ALL).length}
      onClear={() => {
        setCategory(ALL);
        setBrand(ALL);
        onChange();
      }}
      filters={
        <>
          <FilterSelect
            label={t("category")}
            value={category}
            onChange={(value) => {
              setCategory(value);
              onChange();
            }}
            options={[{ value: ALL, label: t("allCategories") }, ...categories]}
          />
          <FilterSelect
            label={t("brand")}
            value={brand}
            onChange={(value) => {
              setBrand(value);
              onChange();
            }}
            options={[{ value: ALL, label: t("allBrands") }, ...brands]}
          />
        </>
      }
    />
  );
  return { params, bar };
}

function ExportButton({ url, name }: { url: string; name: string }) {
  const t = useTranslations("stock.reports");
  const errors = useErrorText();
  return (
    <Button
      variant="outline"
      className="min-h-10"
      onClick={() =>
        void downloadFile(url, name).catch((err: unknown) => toast.error(errors.message(err)))
      }
    >
      <Download aria-hidden />
      {t("exportExcel")}
    </Button>
  );
}

export function LowStockReport() {
  const t = useTranslations("stock.reports");
  const cursor = useCursor();
  const filters = useReportFilters();
  const summary = useReportsLowStockSummary(filters.params);
  const query = useReportsLowStock({ ...filters.params, cursor: cursor.cursor });
  const page = query.data?.data;
  const unset = summary.data?.data.without_reorder_level ?? 0;

  const columns: DataTableColumn<LowStockRow>[] = [
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
      cell: ({ row }) => <QtyText value={row.original.available} unit={row.original.unit.code} />,
    },
    {
      id: "reorder",
      header: t("reorderLevel"),
      cell: ({ row }) => <QtyText value={row.original.reorder_level} />,
    },
    {
      id: "short",
      header: t("shortBy"),
      cell: ({ row }) => (
        <QtyText value={row.original.shortfall} className="text-warning-strong font-semibold" />
      ),
    },
    { id: "category", header: t("category"), cell: ({ row }) => row.original.category || "—" },
    { id: "brand", header: t("brand"), cell: ({ row }) => row.original.brand || "—" },
  ];

  return (
    <>
      <PageHeader
        title={t("lowTitle")}
        description={t("lowDescription")}
        actions={
          <ExportButton url={getReportsLowStockExportUrl(filters.params)} name="low-stock.xlsx" />
        }
      />
      {unset > 0 ? (
        <Link
          href="/manage/stock?status=NO_REORDER_LEVEL"
          className="border-info/40 bg-info/10 mb-4 flex min-h-11 items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
        >
          <span>{t("withoutReorder", { count: unset })}</span>
          <span className="text-primary shrink-0 font-medium">{t("setThem")}</span>
        </Link>
      ) : null}
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["available", "reorder", "short"]}
        pagination={cursor.pagination(page)}
        caption={t("lowTitle")}
        empty={{ title: t("noLowTitle"), description: t("noLowBody") }}
        cardLayout={{
          product: "title",
          available: "primary",
          short: "primary",
          reorder: "secondary",
          category: "secondary",
          brand: "secondary",
        }}
        toolbar={filters.bar(cursor.reset)}
      />
    </>
  );
}

function BucketTable({ title, rows }: { title: string; rows: Bucket[] }) {
  const t = useTranslations("stock.reports");
  const columns: DataTableColumn<Bucket>[] = [
    { id: "name", header: title, cell: ({ row }) => row.original.name || t("none") },
    { id: "products", header: t("products"), cell: ({ row }) => row.original.products },
    {
      id: "value",
      header: t("value"),
      cell: ({ row }) => <MoneyText value={row.original.value} />,
    },
    {
      id: "missing",
      header: t("noCost"),
      cell: ({ row }) =>
        row.original.missing_cost ? (
          <span className="text-warning-strong font-medium">{row.original.missing_cost}</span>
        ) : (
          "0"
        ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row) => row.name || "(none)"}
      numericColumns={["products", "value", "missing"]}
      caption={title}
      empty={{ title: t("noStock") }}
      cardLayout={{ name: "title", value: "primary", products: "primary", missing: "secondary" }}
    />
  );
}

export function ValuationReport() {
  const t = useTranslations("stock.reports");
  const { can } = useAuth();
  if (!canSeeValuation(can)) {
    return <EmptyState title={t("valuationTitle")} description={t("valuationNoAccess")} />;
  }
  return <Valuation />;
}

function Valuation() {
  const t = useTranslations("stock.reports");
  const cursor = useCursor();
  const filters = useReportFilters();
  const [missingOnly, setMissingOnly] = useState(false);
  const [groupBy, setGroupBy] = useState<"category" | "brand">("category");
  const totals = useReportsStockValuation(filters.params);
  const query = useReportsStockValuationProducts({
    ...filters.params,
    cursor: cursor.cursor,
    missing_cost: missingOnly || undefined,
  });
  const page = query.data?.data;
  const data = totals.data?.data;

  const columns: DataTableColumn<ValuationRow>[] = [
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
      id: "on_hand",
      header: t("onHand"),
      cell: ({ row }) => <QtyText value={row.original.on_hand} unit={row.original.unit.code} />,
    },
    {
      id: "cost",
      header: t("costPrice"),
      cell: ({ row }) =>
        row.original.cost_price ? (
          <MoneyText value={row.original.cost_price} />
        ) : (
          <span className="text-warning-strong font-medium">{t("noCostPrice")}</span>
        ),
    },
    {
      id: "value",
      header: t("value"),
      cell: ({ row }) => (row.original.value ? <MoneyText value={row.original.value} /> : "—"),
    },
    { id: "category", header: t("category"), cell: ({ row }) => row.original.category || "—" },
  ];

  if (totals.error) {
    return <ErrorState error={totals.error} onRetry={() => void totals.refetch()} />;
  }
  return (
    <>
      <PageHeader
        title={t("valuationTitle")}
        description={t("valuationDescription")}
        actions={
          <ExportButton
            url={getReportsStockValuationExportUrl(filters.params)}
            name="stock-valuation.xlsx"
          />
        }
      />
      <div className="mb-4">{filters.bar(cursor.reset)}</div>
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <CountCard
          label={t("totalValue")}
          value={data ? <MoneyText value={data.total_value} /> : "—"}
        />
        <CountCard label={t("productsValued")} value={data?.products_valued ?? "—"} />
        <CountCard
          label={t("withoutCost")}
          value={data?.missing_cost ?? "—"}
          tone={data?.missing_cost ? "warning" : undefined}
          active={missingOnly}
          onClick={() => {
            setMissingOnly(!missingOnly);
            cursor.reset();
          }}
        />
      </div>
      {data?.missing_cost ? (
        <p className="text-muted-foreground mb-4 text-sm">{t("missingNote")}</p>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
        <section aria-labelledby="valuation-products" className="min-w-0 space-y-3">
          <h2 id="valuation-products" className="text-lg font-semibold">
            {missingOnly ? t("missingTitle") : t("productsTitle")}
          </h2>
          <DataTable
            columns={columns}
            data={page?.results ?? []}
            getRowId={(row) => row.id}
            isLoading={query.isLoading}
            error={query.error}
            onRetry={() => void query.refetch()}
            numericColumns={["on_hand", "cost", "value"]}
            pagination={cursor.pagination(page)}
            caption={t("productsTitle")}
            empty={{ title: t("noStock"), description: t("noStockBody") }}
            cardLayout={{
              product: "title",
              value: "primary",
              cost: "primary",
              on_hand: "secondary",
              category: "secondary",
            }}
          />
        </section>
        <Card className="h-fit">
          <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
            <CardTitle className="text-base">{t("totalsBy")}</CardTitle>
            <div role="tablist" aria-label={t("totalsBy")} className="flex gap-1">
              {(["category", "brand"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={groupBy === value}
                  onClick={() => setGroupBy(value)}
                  className={cn(
                    "min-h-11 min-w-11 rounded-full border px-3 text-sm md:min-h-9 md:min-w-0",
                    groupBy === value
                      ? "border-brand-200 bg-brand-50 font-medium"
                      : "hover:bg-muted",
                  )}
                >
                  {t(value)}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent>
            <BucketTable
              title={t(groupBy)}
              rows={data ? (groupBy === "category" ? data.by_category : data.by_brand) : []}
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
