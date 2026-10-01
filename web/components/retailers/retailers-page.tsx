"use client";

import { Download, FileUp, Plus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { RetailersNav } from "@/components/insights/shop-activity";
import { FilterSelect, PickDialog } from "@/components/catalog/controls";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filter-bar";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getRetailersExportUrl } from "@/lib/api/generated/endpoints/imports/imports";
import { retailersBulk, useRetailersList } from "@/lib/api/generated/endpoints/retailers/retailers";
import type { RetailerBulkActionEnum, RetailerList } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";
import { formatIndianMobile } from "@/lib/utils";
import { useListSearch } from "@/lib/list-search";

import { usePriceListOptions, useSalespeopleOptions } from "./options";

const ALL = "all";

export function RetailersPage() {
  const t = useTranslations("retailers.list");
  const { can } = useAuth();
  const errors = useErrorText();
  const manage = can("retailers.manage");
  const priceLists = usePriceListOptions();
  const salespeople = useSalespeopleOptions();
  const [search, setSearch] = useListSearch();
  const [status, setStatus] = useState(ALL);
  const [salesperson, setSalesperson] = useState(ALL);
  const [priceList, setPriceList] = useState(ALL);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());

  const query = useRetailersList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    status: status === ALL ? undefined : (status as RetailerList["status"]),
    salesperson: salesperson === ALL ? undefined : salesperson,
    price_list: priceList === ALL ? undefined : priceList,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];

  function filtered(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      cursor.reset();
      setSelected(new Set());
    };
  }

  async function bulk(action: RetailerBulkActionEnum, value?: string) {
    try {
      const result = await retailersBulk({
        retailer_ids: [...selected],
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
      await downloadFile(getRetailersExportUrl({ file_type: fileType }), `retailers.${fileType}`);
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const columns: DataTableColumn<RetailerList>[] = [
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <Link href={`/manage/retailers/${row.original.id}`} className="block hover:underline">
          <span className="block font-medium">{row.original.shop_name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.code}
            {row.original.owner_name ? ` · ${row.original.owner_name}` : ""}
          </span>
        </Link>
      ),
    },
    {
      id: "mobile",
      header: t("mobile"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap">{formatIndianMobile(row.original.mobile)}</span>
      ),
    },
    { id: "gstin", header: t("gstin"), cell: ({ row }) => row.original.gstin ?? "—" },
    {
      id: "priceList",
      header: t("priceList"),
      cell: ({ row }) => row.original.price_list?.name ?? t("standardPrices"),
    },
    {
      id: "salesperson",
      header: t("salesperson"),
      cell: ({ row }) => row.original.salesperson?.full_name ?? "—",
    },
    {
      id: "credit",
      header: t("creditLimit"),
      cell: ({ row }) =>
        row.original.credit_limit ? <MoneyText value={row.original.credit_limit} /> : "—",
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
  ];

  const filtering = Boolean(debounced) || [status, salesperson, priceList].some((f) => f !== ALL);
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
                  <Link href="/manage/imports/new?kind=RETAILERS">
                    <FileUp aria-hidden />
                    {t("import")}
                  </Link>
                </Button>
                <Button asChild className="min-h-10">
                  <Link href="/manage/retailers/new">
                    <Plus aria-hidden />
                    {t("add")}
                  </Link>
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <RetailersNav />
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["credit"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          filtering
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : {
                title: t("emptyTitle"),
                description: t("emptyBody"),
                action: manage ? (
                  <Button asChild className="min-h-11">
                    <Link href="/manage/imports/new?kind=RETAILERS">{t("importFirst")}</Link>
                  </Button>
                ) : undefined,
              }
        }
        cardLayout={{
          shop: "title",
          mobile: "primary",
          priceList: "primary",
          status: "primary",
          gstin: "secondary",
          salesperson: "secondary",
          credit: "secondary",
        }}
        selection={
          manage
            ? {
                selected,
                onChange: setSelected,
                pageLabel: t("selectPage"),
                rowLabel: (row) => t("selectRow", { name: row.shop_name }),
                regionLabel: t("bulkLabel"),
                actions: (
                  <>
                    <PickDialog
                      trigger={t("assignSalesperson")}
                      title={t("assignSalespersonTitle", { count: selected.size })}
                      label={t("salesperson")}
                      options={salespeople}
                      onPick={(value) => bulk("assign_salesperson", value)}
                    />
                    {can("pricing.manage") ? (
                      <PickDialog
                        trigger={t("assignPriceList")}
                        title={t("assignPriceListTitle", { count: selected.size })}
                        label={t("priceList")}
                        options={priceLists}
                        onPick={(value) => bulk("assign_price_list", value)}
                      />
                    ) : null}
                    <ReasonDialog
                      trigger={
                        <Button size="sm" variant="outline">
                          {t("putOnHold")}
                        </Button>
                      }
                      title={t("putOnHoldTitle", { count: selected.size })}
                      description={t("putOnHoldBody")}
                      reasonLabel={t("reason")}
                      confirmLabel={t("putOnHold")}
                      destructive
                      onConfirm={(reason) => bulk("block", reason)}
                    />
                    <ConfirmDialog
                      trigger={
                        <Button size="sm" variant="outline">
                          {t("removeHold")}
                        </Button>
                      }
                      title={t("removeHoldTitle", { count: selected.size })}
                      confirmLabel={t("removeHold")}
                      onConfirm={() => bulk("unblock")}
                    />
                  </>
                ),
              }
            : undefined
        }
        toolbar={
          <FilterBar
            active={[status, salesperson, priceList].filter((f) => f !== ALL).length}
            onClear={() => {
              for (const reset of [setStatus, setSalesperson, setPriceList]) reset(ALL);
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
                  onChange={filtered(setStatus)}
                  options={[
                    { value: ALL, label: t("anyStatus") },
                    { value: "ACTIVE", label: t("active") },
                    { value: "BLOCKED", label: t("onHold") },
                  ]}
                />
                <FilterSelect
                  label={t("salesperson")}
                  value={salesperson}
                  onChange={filtered(setSalesperson)}
                  options={[{ value: ALL, label: t("anySalesperson") }, ...salespeople]}
                />
                {priceLists.length ? (
                  <FilterSelect
                    label={t("priceList")}
                    value={priceList}
                    onChange={filtered(setPriceList)}
                    options={[{ value: ALL, label: t("anyPriceList") }, ...priceLists]}
                  />
                ) : null}
              </>
            }
          />
        }
      />
    </>
  );
}
