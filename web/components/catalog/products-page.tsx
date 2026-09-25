"use client";

import { Download, FileUp, ImageOff, Plus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  catalogProductsBulk,
  useCatalogProductsList,
} from "@/lib/api/generated/endpoints/catalog/catalog";
import { getProductsExportUrl } from "@/lib/api/generated/endpoints/imports/imports";
import type { BulkActionEnum, ProductList } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";

import { FilterSelect, PickDialog } from "./controls";
import { percent, useBrandOptions, useCategoryOptions } from "./options";

const ALL = "all";

export function ProductsPage() {
  const t = useTranslations("catalog.products");
  const { can } = useAuth();
  const errors = useErrorText();
  const manage = can("products.manage");
  const categories = useCategoryOptions();
  const brands = useBrandOptions();

  const [search, setSearch] = useState("");
  const [category, setCategory] = useState(ALL);
  const [brand, setBrand] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [shop, setShop] = useState(ALL);
  const [own, setOwn] = useState(ALL);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());

  const query = useCatalogProductsList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    category: category === ALL ? undefined : category,
    brand: brand === ALL ? undefined : brand,
    is_active: status === ALL ? undefined : status === "active",
    show_in_shop: shop === ALL ? undefined : shop === "shown",
    own_brand: own === ALL ? undefined : own === "own",
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];

  function filtered<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      cursor.reset();
      setSelected(new Set());
    };
  }

  async function bulk(action: BulkActionEnum, value?: string) {
    try {
      const result = await catalogProductsBulk({
        product_ids: [...selected],
        action,
        value: value ?? null,
      });
      toast.success(t("bulkDone", { count: result.data.changed }));
      setSelected(new Set());
      void query.refetch();
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  async function exportAs(fileType: "xlsx" | "csv") {
    try {
      await downloadFile(getProductsExportUrl({ file_type: fileType }), `products.${fileType}`);
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const allOnPage = rows.length > 0 && rows.every((row) => selected.has(row.id));
  const columns: DataTableColumn<ProductList>[] = [
    ...(manage
      ? [
          {
            id: "select",
            header: () => (
              <Checkbox
                aria-label={t("selectPage")}
                checked={allOnPage}
                onCheckedChange={(checked) =>
                  setSelected(checked ? new Set(rows.map((r) => r.id)) : new Set())
                }
              />
            ),
            cell: ({ row }) => (
              <Checkbox
                aria-label={t("selectRow", { name: row.original.name })}
                checked={selected.has(row.original.id)}
                onCheckedChange={(checked) =>
                  setSelected((current) => {
                    const next = new Set(current);
                    if (checked) next.add(row.original.id);
                    else next.delete(row.original.id);
                    return next;
                  })
                }
              />
            ),
          } satisfies DataTableColumn<ProductList>,
        ]
      : []),
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <Link
          href={`/manage/products/${row.original.id}`}
          className="flex min-h-10 items-center gap-3 hover:underline"
        >
          {row.original.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image
            <img
              src={row.original.thumbnail_url}
              alt=""
              className="size-10 shrink-0 rounded-md border object-cover"
            />
          ) : (
            <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-md">
              <ImageOff aria-hidden className="size-4" />
            </span>
          )}
          <span className="min-w-0">
            <span className="block font-medium">{row.original.name}</span>
            <span className="text-muted-foreground block text-xs">{row.original.code}</span>
          </span>
        </Link>
      ),
    },
    {
      id: "category",
      header: t("category"),
      cell: ({ row }) => row.original.category?.name ?? "—",
    },
    { id: "brand", header: t("brand"), cell: ({ row }) => row.original.brand?.name ?? "—" },
    {
      id: "price",
      header: t("price"),
      cell: ({ row }) => <MoneyText value={row.original.base_price} />,
    },
    {
      id: "mrp",
      header: t("mrp"),
      cell: ({ row }) => (row.original.mrp ? <MoneyText value={row.original.mrp} /> : "—"),
    },
    {
      id: "gst",
      header: t("gst"),
      cell: ({ row }) =>
        row.original.gst_rate ? (
          percent(row.original.gst_rate)
        ) : (
          <Badge variant="outline">{t("noRate")}</Badge>
        ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="flex flex-wrap gap-1">
          <StatusBadge status={row.original.is_active ? "ACTIVE" : "INACTIVE"} />
          {row.original.show_in_shop ? null : <Badge variant="outline">{t("hidden")}</Badge>}
          {row.original.own_brand ? <Badge variant="secondary">{t("ownBrand")}</Badge> : null}
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="min-h-10">
                  <Download aria-hidden />
                  {t("export")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => void exportAs("xlsx")}>
                  {t("exportExcel")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void exportAs("csv")}>
                  {t("exportCsv")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {manage ? (
              <>
                <Button asChild variant="outline" className="min-h-10">
                  <Link href="/manage/imports/new?kind=PRODUCTS">
                    <FileUp aria-hidden />
                    {t("import")}
                  </Link>
                </Button>
                <Button asChild className="min-h-10">
                  <Link href="/manage/products/new">
                    <Plus aria-hidden />
                    {t("add")}
                  </Link>
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["price", "mrp", "gst"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          debounced || [category, brand, status, shop, own].some((f) => f !== ALL)
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : {
                title: t("emptyTitle"),
                description: t("emptyBody"),
                action: manage ? (
                  <Button asChild className="min-h-11">
                    <Link href="/manage/imports/new?kind=PRODUCTS">{t("importFirst")}</Link>
                  </Button>
                ) : undefined,
              }
        }
        toolbar={
          <>
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
            <FilterSelect
              label={t("category")}
              value={category}
              onChange={filtered(setCategory)}
              options={[{ value: ALL, label: t("allCategories") }, ...categories]}
            />
            <FilterSelect
              label={t("brand")}
              value={brand}
              onChange={filtered(setBrand)}
              options={[{ value: ALL, label: t("allBrands") }, ...brands]}
            />
            <FilterSelect
              label={t("status")}
              value={status}
              onChange={filtered(setStatus)}
              options={[
                { value: ALL, label: t("anyStatus") },
                { value: "active", label: t("active") },
                { value: "inactive", label: t("inactive") },
              ]}
            />
            <FilterSelect
              label={t("shop")}
              value={shop}
              onChange={filtered(setShop)}
              options={[
                { value: ALL, label: t("shownAndHidden") },
                { value: "shown", label: t("shown") },
                { value: "hidden", label: t("hiddenOnly") },
              ]}
            />
            <FilterSelect
              label={t("ownBrandFilter")}
              value={own}
              onChange={filtered(setOwn)}
              options={[
                { value: ALL, label: t("allBrandTypes") },
                { value: "own", label: t("ownBrandOnly") },
                { value: "traded", label: t("tradedOnly") },
              ]}
            />
            {selected.size > 0 ? (
              <div
                role="region"
                aria-label={t("bulkLabel")}
                className="bg-brand-50 flex w-full flex-wrap items-center gap-2 rounded-lg p-2"
              >
                <span className="text-sm font-medium">
                  {t("selected", { count: selected.size })}
                </span>
                <Button size="sm" variant="outline" onClick={() => void bulk("activate")}>
                  {t("activate")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => void bulk("deactivate")}>
                  {t("deactivate")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => void bulk("show_in_shop")}>
                  {t("showInShop")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => void bulk("hide_from_shop")}>
                  {t("hideFromShop")}
                </Button>
                <PickDialog
                  trigger={t("setCategory")}
                  title={t("setCategoryTitle", { count: selected.size })}
                  label={t("category")}
                  options={categories}
                  onPick={(value) => bulk("set_category", value)}
                />
                <PickDialog
                  trigger={t("setBrand")}
                  title={t("setBrandTitle", { count: selected.size })}
                  label={t("brand")}
                  options={brands}
                  onPick={(value) => bulk("set_brand", value)}
                />
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                  {t("clearSelection")}
                </Button>
              </div>
            ) : null}
          </>
        }
      />
    </>
  );
}
