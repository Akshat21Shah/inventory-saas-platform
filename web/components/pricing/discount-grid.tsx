"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { WarningList } from "@/components/catalog/product-editor";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  retailersDiscountGridPreview,
  retailersDiscountGridSave,
  useRetailersDiscountGrid,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import { useRetailersRetrieve } from "@/lib/api/generated/endpoints/retailers/retailers";
import type { DiscountTypeEnum, GridPrice, GridRow, Warning } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

const ALL = "all";
const clean = (v: string) => v.trim().replaceAll(",", "");

interface Edit {
  discount_type: DiscountTypeEnum;
  value: string; // "" removes the shop's discount on the product
}

function NetPrice({ price, pending }: { price: GridPrice | undefined; pending: boolean }) {
  const t = useTranslations("pricing.grid");
  if (pending || !price) return <span className="text-muted-foreground">…</span>;
  return (
    <span className="flex flex-col items-end">
      <MoneyText value={price.net_unit_price} className="font-medium" />
      {price.discount_total !== "0.00" ? (
        <span className="text-muted-foreground text-xs">
          {t("off", { percent: formatQty(price.discount_percent, 2) })}
        </span>
      ) : null}
    </span>
  );
}

function DiscountEditor({
  row,
  edit,
  disabled,
  onChange,
}: {
  row: GridRow;
  edit: Edit | undefined;
  disabled: boolean;
  onChange: (edit: Edit) => void;
}) {
  const t = useTranslations("pricing.grid");
  const current: Edit = edit ?? {
    discount_type: (row.simple?.discount_type as DiscountTypeEnum | undefined) ?? "PERCENT",
    value: row.simple?.value ?? "",
  };
  return (
    <span className="flex items-center justify-end gap-1">
      <Select
        value={current.discount_type}
        disabled={disabled}
        onValueChange={(v) => onChange({ ...current, discount_type: v as DiscountTypeEnum })}
      >
        <SelectTrigger
          className="min-h-10 w-20"
          aria-label={t("typeFor", { name: row.product.name })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="PERCENT">%</SelectItem>
          <SelectItem value="FLAT_PER_UNIT">{t("flat")}</SelectItem>
        </SelectContent>
      </Select>
      <Input
        inputMode="decimal"
        value={current.value}
        disabled={disabled}
        placeholder="0"
        onChange={(e) => onChange({ ...current, value: e.target.value })}
        aria-label={t("valueFor", { name: row.product.name })}
        className="h-10 w-24 text-right tabular-nums"
      />
    </span>
  );
}

export function DiscountGridPage({ retailerId }: { retailerId: string }) {
  const t = useTranslations("pricing.grid");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const shop = useRetailersRetrieve(retailerId).data?.data;
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState(ALL);
  const [brand, setBrand] = useState(ALL);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<readonly Warning[]>([]);
  const [saving, setSaving] = useState(false);
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const query = useRetailersDiscountGrid(retailerId, {
    cursor: cursor.cursor,
    search: debounced || undefined,
    category: category === ALL ? undefined : category,
    brand: brand === ALL ? undefined : brand,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];

  // Live net prices for edited rows, worked out by the server (nothing is saved).
  const dirty = Object.entries(edits).map(([product, e]) => ({
    product,
    discount_type: e.discount_type,
    value: clean(e.value) || null,
  }));
  const pendingKey = useDebounced(JSON.stringify(dirty), 400);
  const preview = useQuery({
    queryKey: ["discount-grid-preview", retailerId, pendingKey],
    enabled: dirty.length > 0 && pendingKey === JSON.stringify(dirty),
    queryFn: async () => {
      const response = await retailersDiscountGridPreview(retailerId, {
        items: JSON.parse(pendingKey) as typeof dirty,
      });
      return Object.fromEntries(response.data.map((r) => [r.product.id, r.price]));
    },
    retry: false,
  });
  const previewPending = pendingKey !== JSON.stringify(dirty) || preview.isFetching;

  async function save() {
    setSaving(true);
    setFieldErrors({});
    try {
      const response = await retailersDiscountGridSave(retailerId, { items: dirty });
      toast.success(t("saved", { count: response.data.changed }));
      setWarnings(response.data.warnings);
      setEdits({});
      void query.refetch();
    } catch (err) {
      const fields = errors.fields(err);
      // "items.3.value" → the product in that position.
      const byProduct: Record<string, string> = {};
      for (const [key, message] of Object.entries(fields)) {
        const index = Number(key.split(".")[1]);
        const product = dirty[index]?.product;
        if (product) byProduct[product] = message;
      }
      setFieldErrors(byProduct);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: DataTableColumn<GridRow>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <span>
          <span className="block font-medium">{row.original.product.name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.product.code}
            {row.original.brand ? ` · ${row.original.brand.name}` : ""}
          </span>
          {row.original.others.map((rule) => (
            <Link key={rule.id} href={`/manage/pricing/discounts/${rule.id}`} className="mr-1">
              <Badge variant="outline" className="mt-1">
                {t("otherRule", { name: rule.name })}
              </Badge>
            </Link>
          ))}
        </span>
      ),
    },
    {
      id: "price",
      header: t("shopPrice"),
      cell: ({ row }) => (
        <span className="flex flex-col items-end">
          <MoneyText value={row.original.price.unit_price} />
          <span className="text-muted-foreground text-xs">
            {t(`source.${row.original.price.price_source}`)}
          </span>
        </span>
      ),
    },
    {
      id: "discount",
      header: t("discount"),
      cell: ({ row }) => (
        <span className="flex flex-col items-end gap-1">
          <DiscountEditor
            row={row.original}
            edit={edits[row.original.product.id]}
            disabled={!manage}
            onChange={(edit) => setEdits((all) => ({ ...all, [row.original.product.id]: edit }))}
          />
          {fieldErrors[row.original.product.id] ? (
            <span role="alert" className="text-destructive text-xs">
              {fieldErrors[row.original.product.id]}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "net",
      header: t("net"),
      cell: ({ row }) => {
        const id = row.original.product.id;
        const edited = id in edits;
        return (
          <NetPrice
            price={edited ? preview.data?.[id] : row.original.price}
            pending={edited && previewPending}
          />
        );
      },
    },
  ];

  const changed = Object.keys(edits).length;
  return (
    <>
      <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
        <Link href={`/manage/retailers/${retailerId}`}>
          <ArrowLeft aria-hidden />
          {shop?.shop_name ?? t("back")}
        </Link>
      </Button>
      <PageHeader
        title={shop ? t("title", { shop: shop.shop_name }) : t("titlePlain")}
        description={t("description")}
      />
      <div className="mb-4">
        <WarningList warnings={warnings} keys={{ FREE_GOODS: "FREE_GOODS_GRID" }} />
      </div>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.product.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["price", "discount", "net"]}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
        toolbar={
          <>
            <Input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                cursor.reset();
              }}
              placeholder={t("search")}
              aria-label={t("search")}
              className="h-10 w-full sm:w-64"
            />
            <FilterSelect
              label={t("category")}
              value={category}
              onChange={(v) => {
                setCategory(v);
                cursor.reset();
              }}
              options={[{ value: ALL, label: t("allCategories") }, ...categories]}
            />
            <FilterSelect
              label={t("brand")}
              value={brand}
              onChange={(v) => {
                setBrand(v);
                cursor.reset();
              }}
              options={[{ value: ALL, label: t("allBrands") }, ...brands]}
            />
          </>
        }
      />
      {manage && changed ? (
        <div className="bg-background sticky bottom-0 mt-4 flex flex-wrap items-center justify-end gap-3 border-t py-3">
          <span className="text-sm">{t("unsaved", { count: changed })}</span>
          <Button variant="outline" className="min-h-11" onClick={() => setEdits({})}>
            {t("discard")}
          </Button>
          <Button className="min-h-11" disabled={saving} onClick={() => void save()}>
            {t("save", { count: changed })}
          </Button>
        </div>
      ) : null}
      <p className="text-muted-foreground mt-4 text-sm">{t("note")}</p>
    </>
  );
}
