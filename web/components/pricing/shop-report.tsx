"use client";

import { Download, FileUp } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  getPricingShopReportExportUrl,
  usePricingShopReport,
  useRetailersFreeProducts,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import type { ReportRow } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";

/** "Export" (Excel/CSV) and "Import" for a pricing screen. */
export function PricingFileActions({
  exportUrl,
  fileName,
  importKind,
}: {
  exportUrl: (fileType: "xlsx" | "csv") => string;
  fileName: string;
  importKind: string;
}) {
  const t = useTranslations("pricing.files");
  const errors = useErrorText();
  const { can } = useAuth();
  const save = async (fileType: "xlsx" | "csv") => {
    try {
      await downloadFile(exportUrl(fileType), `${fileName}.${fileType}`);
    } catch (err) {
      toast.error(errors.message(err));
    }
  };
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" className="min-h-10">
            <Download aria-hidden />
            {t("export")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => void save("xlsx")}>{t("excel")}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void save("csv")}>{t("csv")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {can("pricing.manage") ? (
        <Button asChild variant="outline" className="min-h-10">
          <Link href={`/manage/imports/new?kind=${importKind}`}>
            <FileUp aria-hidden />
            {t("import")}
          </Link>
        </Button>
      ) : null}
    </>
  );
}

function FreeProducts({ shop }: { shop: ReportRow }) {
  const t = useTranslations("pricing.report");
  const [open, setOpen] = useState(false);
  const query = useRetailersFreeProducts(shop.id, { query: { enabled: open } });
  if (!shop.free_product_count) return <span className="text-muted-foreground">0</span>;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="link" className="text-warning-strong h-auto p-0 font-semibold">
          {shop.free_product_count}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("freeTitle", { shop: shop.shop_name })}</DialogTitle>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">{t("freeBody")}</p>
        <ul className="max-h-64 overflow-y-auto text-sm">
          {(query.data?.data ?? []).map((p) => (
            <li key={p.id}>
              {p.name} ({p.code})
            </li>
          ))}
        </ul>
        <Button asChild variant="outline" className="min-h-10">
          <Link href={`/manage/retailers/${shop.id}/discounts`}>{t("openGrid")}</Link>
        </Button>
      </DialogContent>
    </Dialog>
  );
}

export function ShopPricingReportPage() {
  const t = useTranslations("pricing.report");
  const errors = useErrorText();
  const [search, setSearch] = useState("");
  const [show, setShow] = useState<"CUSTOMISED" | "ALL">("CUSTOMISED");
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const query = usePricingShopReport({
    cursor: cursor.cursor,
    search: debounced || undefined,
    show,
  });
  const page = query.data?.data;
  const columns: DataTableColumn<ReportRow>[] = [
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <Link href={`/manage/retailers/${row.original.id}`} className="hover:underline">
          <span className="block font-medium">{row.original.shop_name}</span>
          <span className="text-muted-foreground block text-xs">{row.original.code}</span>
        </Link>
      ),
    },
    {
      id: "list",
      header: t("priceList"),
      cell: ({ row }) => row.original.price_list?.name ?? t("standard"),
    },
    {
      id: "special",
      header: t("specialPrices"),
      cell: ({ row }) =>
        row.original.special_price_count ? (
          <Link
            href={`/manage/pricing/special-prices?retailer=${row.original.id}`}
            className="hover:underline"
          >
            {row.original.special_price_count}
          </Link>
        ) : (
          0
        ),
    },
    {
      id: "rules",
      header: t("shopRules"),
      cell: ({ row }) =>
        row.original.shop_rule_count ? (
          <Link href={`/manage/retailers/${row.original.id}/discounts`} className="hover:underline">
            {row.original.shop_rule_count}
          </Link>
        ) : (
          0
        ),
    },
    { id: "free", header: t("free"), cell: ({ row }) => <FreeProducts shop={row.original} /> },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button
            variant="outline"
            className="min-h-10"
            onClick={() =>
              void downloadFile(getPricingShopReportExportUrl(), "shop-pricing.xlsx").catch(
                (err: unknown) => toast.error(errors.message(err)),
              )
            }
          >
            <Download aria-hidden />
            {t("export")}
          </Button>
        }
      />
      <DataTable
        columns={columns}
        cardLayout={{
          shop: "title",
          list: "primary",
          special: "primary",
          rules: "primary",
          free: "primary",
        }}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["special", "rules", "free"]}
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
              label={t("show")}
              value={show}
              onChange={(v) => {
                setShow(v as "CUSTOMISED" | "ALL");
                cursor.reset();
              }}
              options={[
                { value: "CUSTOMISED", label: t("customised") },
                { value: "ALL", label: t("all") },
              ]}
            />
          </>
        }
      />
      <p className="text-muted-foreground mt-4 text-sm">{t("freeNote")}</p>
    </>
  );
}
