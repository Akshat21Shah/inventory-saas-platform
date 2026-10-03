"use client";

import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { BillingNav } from "@/components/billing/billing-nav";
import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Input } from "@/components/ui/input";
import {
  useEinvoicesList,
  useEwaybillsList,
} from "@/lib/api/generated/endpoints/compliance/compliance";
import {
  EinvoicesListDocumentType,
  EinvoicesListStatus,
  EwaybillsListStatus,
  type EInvoiceRow,
  type EWayBillRow,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useDebounced } from "@/lib/use-debounced";
import { ProviderMessage } from "@/components/shared/provider-message";
import { useGstFailure } from "./provider-line";

const ALL = "all";

/** A status, and the portal's reason when it failed (shown under the badge). */
function StatusCell({
  status,
  labels,
  code,
  error,
}: {
  status: string;
  labels: "einvoiceStatus" | "ewaybillStatus";
  code: string;
  error: string;
}) {
  const gst = useGstFailure();
  return (
    <span className="space-y-1">
      <StatusBadge status={status} labels={labels} />
      {status === "FAILED" ? (
        <ProviderMessage
          {...gst(labels === "einvoiceStatus" ? "einvoice" : "ewaybill", code, error)}
          compact
          className="text-destructive max-w-72 text-xs"
        />
      ) : null}
    </span>
  );
}

function documentHref(row: EInvoiceRow): string {
  return row.document_type === "INVOICE"
    ? `/manage/invoices/${row.document_id}`
    : `/manage/invoices/credit-notes/${row.document_id}`;
}

function EInvoicesList() {
  const t = useTranslations("compliance.lists");
  const statuses = useTranslations("einvoiceStatus");
  const cursor = useCursor();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>(ALL);
  const [kind, setKind] = useState<string>(ALL);
  const term = useDebounced(search.trim(), 300);
  const query = useEinvoicesList({
    cursor: cursor.cursor,
    search: term || undefined,
    status: status === ALL ? undefined : (status as EinvoicesListStatus),
    document_type: kind === ALL ? undefined : (kind as EinvoicesListDocumentType),
  });
  const page = query.data?.data;
  const columns: DataTableColumn<EInvoiceRow>[] = [
    {
      id: "document",
      header: t("document"),
      cell: ({ row }) => (
        <Link
          href={`${documentHref(row.original)}#einvoice`}
          className="text-brand-700 font-medium hover:underline"
        >
          {t(`kinds.${row.original.document_type}`, { number: row.original.document_number })}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.shop_name },
    {
      id: "date",
      header: t("date"),
      cell: ({ row }) => <DateText value={row.original.document_date} />,
    },
    {
      id: "total",
      header: t("total"),
      cell: ({ row }) => <MoneyText value={row.original.grand_total} />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <StatusCell
          status={row.original.status}
          labels="einvoiceStatus"
          code={row.original.error_code}
          error={row.original.error_message}
        />
      ),
    },
    {
      id: "reportBy",
      header: t("reportBy"),
      cell: ({ row }) =>
        row.original.report_by && !["GENERATED", "CANCELLED"].includes(row.original.status) ? (
          <span className={row.original.past_report_by ? "text-destructive font-medium" : ""}>
            <DateText value={row.original.report_by} />
          </span>
        ) : (
          "—"
        ),
    },
    {
      id: "irn",
      header: t("ackNo"),
      cell: ({ row }) => row.original.ack_no || "—",
    },
  ];
  const active = [term, status !== ALL, kind !== ALL].filter(Boolean).length;
  return (
    <DataTable
      columns={columns}
      data={page?.results ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      numericColumns={["total"]}
      pagination={cursor.pagination(page)}
      caption={t("einvoicesTitle")}
      empty={{ title: t("einvoicesEmpty"), description: t("einvoicesEmptyBody") }}
      cardLayout={{
        document: "title",
        shop: "primary",
        status: "primary",
        reportBy: "primary",
        date: "secondary",
        total: "secondary",
        irn: "secondary",
      }}
      toolbar={
        <FilterBar
          active={active}
          onClear={() => {
            setSearch("");
            setStatus(ALL);
            setKind(ALL);
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
              placeholder={t("einvoicesSearch")}
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
                  ...Object.values(EinvoicesListStatus).map((value) => ({
                    value,
                    label: statuses(value),
                  })),
                ]}
              />
              <FilterSelect
                label={t("documentType")}
                value={kind}
                onChange={(value) => {
                  setKind(value);
                  cursor.reset();
                }}
                options={[
                  { value: ALL, label: t("allDocuments") },
                  ...Object.values(EinvoicesListDocumentType).map((value) => ({
                    value,
                    label: t(`documentTypes.${value}`),
                  })),
                ]}
              />
            </>
          }
        />
      }
    />
  );
}

function EWayBillsList() {
  const t = useTranslations("compliance.lists");
  const statuses = useTranslations("ewaybillStatus");
  const cursor = useCursor();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>(ALL);
  const term = useDebounced(search.trim(), 300);
  const query = useEwaybillsList({
    cursor: cursor.cursor,
    search: term || undefined,
    status: status === ALL ? undefined : (status as EwaybillsListStatus),
  });
  const page = query.data?.data;
  const columns: DataTableColumn<EWayBillRow>[] = [
    {
      id: "invoice",
      header: t("invoice"),
      cell: ({ row }) => (
        <Link
          href={`/manage/invoices/${row.original.invoice_id}#ewaybill`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.invoice_number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.shop_name },
    {
      id: "number",
      header: t("ewbNumber"),
      cell: ({ row }) => row.original.ewb_number || "—",
    },
    {
      id: "vehicle",
      header: t("vehicle"),
      cell: ({ row }) => row.original.vehicle_number || "—",
    },
    {
      id: "shipment",
      header: t("shipment"),
      cell: ({ row }) => row.original.shipment_number || "—",
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <StatusCell
          status={row.original.status}
          labels="ewaybillStatus"
          code={row.original.error_code}
          error={row.original.error_message}
        />
      ),
    },
    {
      id: "validUntil",
      header: t("validUntil"),
      cell: ({ row }) =>
        row.original.valid_until ? <DateText value={row.original.valid_until} withTime /> : "—",
    },
    {
      id: "value",
      header: t("value"),
      cell: ({ row }) => <MoneyText value={row.original.consignment_value} />,
    },
  ];
  const active = [term, status !== ALL].filter(Boolean).length;
  return (
    <DataTable
      columns={columns}
      data={page?.results ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      numericColumns={["value"]}
      pagination={cursor.pagination(page)}
      caption={t("ewaybillsTitle")}
      empty={{ title: t("ewaybillsEmpty"), description: t("ewaybillsEmptyBody") }}
      cardLayout={{
        invoice: "title",
        shop: "primary",
        status: "primary",
        vehicle: "primary",
        number: "primary",
        shipment: "secondary",
        validUntil: "secondary",
        value: "secondary",
      }}
      toolbar={
        <FilterBar
          active={active}
          onClear={() => {
            setSearch("");
            setStatus(ALL);
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
              placeholder={t("ewaybillsSearch")}
              aria-label={t("search")}
              className="min-h-10"
            />
          }
          filters={
            <FilterSelect
              label={t("status")}
              value={status}
              onChange={(value) => {
                setStatus(value);
                cursor.reset();
              }}
              options={[
                { value: ALL, label: t("allStatuses") },
                ...Object.values(EwaybillsListStatus).map((value) => ({
                  value,
                  label: statuses(value),
                })),
              ]}
            />
          }
        />
      }
    />
  );
}

/** Invoices → E-invoices: every IRN request, failures first to fix (ADR-049). */
export function EInvoicesPage() {
  const t = useTranslations("compliance.lists");
  const { feature } = useAuth();
  return (
    <>
      <PageHeader title={t("einvoicesTitle")} description={t("einvoicesDescription")} />
      <BillingNav />
      {feature("einvoice") ? (
        <EInvoicesList />
      ) : (
        <EmptyState title={t("einvoicesOff")} description={t("offBody")} />
      )}
    </>
  );
}

/** Invoices → E-way bills: made on dispatch or by hand; failures name the portal's reason. */
export function EWayBillsPage() {
  const t = useTranslations("compliance.lists");
  const { feature } = useAuth();
  return (
    <>
      <PageHeader title={t("ewaybillsTitle")} description={t("ewaybillsDescription")} />
      <BillingNav />
      {feature("ewaybill") ? (
        <EWayBillsList />
      ) : (
        <EmptyState title={t("ewaybillsOff")} description={t("offBody")} />
      )}
    </>
  );
}
