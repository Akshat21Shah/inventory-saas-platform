"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, FilePlus2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getInvoicesRetrieveQueryKey,
  invoicesPdf,
  invoicesRegeneratePdf,
  useInvoicesList,
  useInvoicesRetrieve,
} from "@/lib/api/generated/endpoints/billing/billing";
import {
  InvoicePaymentStatusEnum,
  type Applied,
  type InvoiceDetail,
  type InvoiceLine,
  type InvoiceRow,
  type InvoicesListPaymentStatus,
  type Totals,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

import { BillingNav } from "./billing-nav";
import { DocumentButton } from "./document-button";

const ALL = "all";

/** Days overdue next to a due date, in plain words. */
export function DueText({ due, daysOverdue }: { due: string; daysOverdue: number }) {
  const t = useTranslations("billing.invoices");
  return (
    <span className="space-y-0.5">
      <DateText value={due} />
      {daysOverdue > 0 ? (
        <span className="text-destructive block text-xs font-medium">
          {t("daysOverdue", { days: daysOverdue })}
        </span>
      ) : null}
    </span>
  );
}

/** The distributor's invoices (PLAN §3.10): search, payment status, overdue and dates. */
export function InvoicesList({ retailerId }: { retailerId?: string } = {}) {
  const t = useTranslations("billing.invoices");
  const statuses = useTranslations("status");
  const cursor = useCursor();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>(ALL);
  const [overdue, setOverdue] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const term = useDebounced(search.trim(), 300);
  const query = useInvoicesList({
    cursor: cursor.cursor,
    search: term || undefined,
    retailer: retailerId,
    payment_status: status === ALL ? undefined : (status as InvoicesListPaymentStatus),
    overdue: overdue || undefined,
    date_from: from || undefined,
    date_to: to || undefined,
  });
  const page = query.data?.data;
  const columns: DataTableColumn<InvoiceRow>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/invoices/${row.original.id}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => row.original.retailer.shop_name,
    },
    {
      id: "date",
      header: t("date"),
      cell: ({ row }) => <DateText value={row.original.invoice_date} />,
    },
    {
      id: "due",
      header: t("due"),
      cell: ({ row }) => (
        <DueText due={row.original.due_date} daysOverdue={row.original.days_overdue} />
      ),
    },
    {
      id: "total",
      header: t("total"),
      cell: ({ row }) => <MoneyText value={row.original.grand_total} />,
    },
    {
      id: "balance",
      header: t("balance"),
      cell: ({ row }) => <MoneyText value={row.original.balance_due} />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.payment_status} />,
    },
  ];
  const active = [term, status !== ALL, overdue, from, to].filter(Boolean).length;
  return (
    <DataTable
      columns={columns}
      data={page?.results ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      numericColumns={["total", "balance"]}
      pagination={cursor.pagination(page)}
      caption={t("title")}
      empty={{ title: t("empty"), description: t("emptyBody") }}
      cardLayout={{
        number: "title",
        shop: "primary",
        balance: "primary",
        status: "primary",
        due: "primary",
        date: "secondary",
        total: "secondary",
      }}
      toolbar={
        <FilterBar
          active={active}
          onClear={() => {
            setSearch("");
            setStatus(ALL);
            setOverdue(false);
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
                  ...Object.values(InvoicePaymentStatusEnum).map((value) => ({
                    value,
                    label: statuses(value),
                  })),
                ]}
              />
              <label className="flex min-h-10 items-center gap-2 text-sm max-md:min-h-11">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={overdue}
                  onChange={(e) => {
                    setOverdue(e.target.checked);
                    cursor.reset();
                  }}
                />
                {t("overdueOnly")}
              </label>
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
  );
}

export function InvoicesPage() {
  const t = useTranslations("billing.invoices");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <BillingNav />
      <InvoicesList />
    </>
  );
}

/** Totals of an invoice or credit note, as printed. */
export function DocumentTotals({
  totals,
  intra,
  totalLabel,
  extra,
}: {
  totals: Totals;
  intra: boolean;
  totalLabel: string;
  extra?: { label: string; value: string; strong?: boolean }[];
}) {
  const t = useTranslations("billing.totals");
  const rows: [string, string][] = [
    [t("taxable"), totals.taxable_total],
    ...((intra
      ? [
          [t("cgst"), totals.cgst_total],
          [t("sgst"), totals.sgst_total],
        ]
      : [[t("igst"), totals.igst_total]]) as [string, string][]),
  ];
  if (totals.cess_total !== "0.00") rows.push([t("cess"), totals.cess_total]);
  if (totals.round_off !== "0.00") rows.push([t("roundOff"), totals.round_off]);
  return (
    <dl className="space-y-1 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-4">
          <dt>{label}</dt>
          <dd>
            <MoneyText value={value} />
          </dd>
        </div>
      ))}
      <div className="flex justify-between gap-4 border-t pt-1 text-base font-semibold">
        <dt>{totalLabel}</dt>
        <dd>
          <MoneyText value={totals.grand_total} />
        </dd>
      </div>
      {extra?.map((row) => (
        <div
          key={row.label}
          className={
            row.strong ? "flex justify-between gap-4 font-semibold" : "flex justify-between gap-4"
          }
        >
          <dt>{row.label}</dt>
          <dd>
            <MoneyText value={row.value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function LineTax({ line, intra }: { line: InvoiceLine; intra: boolean }) {
  const t = useTranslations("billing.invoices");
  const tax = intra
    ? t("intraTax", { rate: formatQty(line.gst_rate) })
    : t("interTax", { rate: formatQty(line.gst_rate) });
  return <span>{tax}</span>;
}

/** Money matched to a document: payments, credit-note credit and credit adjustments. */
export function AppliedList({ rows }: { rows: Applied[] }) {
  const t = useTranslations("billing.applied");
  if (!rows.length) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  return (
    <ul className="divide-y rounded-xl border text-sm">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
          <span className="min-w-0">
            {row.source_type === "PAYMENT" ? (
              <Link
                href={`/manage/payments/${row.source_id}`}
                className="font-medium hover:underline"
              >
                {t("payment", { number: row.source_number })}
              </Link>
            ) : row.source_type === "CREDIT_NOTE" ? (
              <Link
                href={`/manage/invoices/credit-notes/${row.source_id}`}
                className="font-medium hover:underline"
              >
                {t("creditNote", { number: row.source_number })}
              </Link>
            ) : (
              <span className="font-medium">{row.source_number}</span>
            )}
            <span className="text-muted-foreground block text-xs">
              <DateText value={row.created_at} withTime />
              {" · "}
              {row.amount.startsWith("-")
                ? t("undone")
                : row.automatic
                  ? t("automatic")
                  : t("byHand")}
              {row.reversed ? ` · ${t("reversed")}` : ""}
            </span>
          </span>
          <MoneyText value={row.amount} className="font-medium" />
        </li>
      ))}
    </ul>
  );
}

function InvoiceActions({ invoice }: { invoice: InvoiceDetail }) {
  const t = useTranslations("billing.invoices");
  const { can } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  return (
    <div className="flex flex-wrap gap-2">
      <DocumentButton fetchLink={() => invoicesPdf(invoice.id)}>{t("download")}</DocumentButton>
      <DocumentButton fetchLink={() => invoicesPdf(invoice.id, { copies: true })}>
        {t("printCopies")}
      </DocumentButton>
      {can("invoices.manage") ? (
        <>
          <Button asChild className="min-h-10 gap-2">
            <Link href={`/manage/invoices/credit-notes/new?invoice=${invoice.id}`}>
              <FilePlus2 aria-hidden className="size-4" />
              {t("creditNote")}
            </Link>
          </Button>
          {invoice.pdf_status === "FAILED" ? (
            <Button
              variant="outline"
              className="min-h-10 gap-2"
              onClick={async () => {
                try {
                  await invoicesRegeneratePdf(invoice.id);
                  toast.success(t("regenerating"));
                  void client.invalidateQueries({
                    queryKey: getInvoicesRetrieveQueryKey(invoice.id),
                  });
                } catch (error) {
                  toast.error(message(error));
                }
              }}
            >
              <RefreshCw aria-hidden className="size-4" />
              {t("regenerate")}
            </Button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** One invoice: lines, tax, what was paid or credited against it, its credit notes. */
export function InvoiceDetailPage({ invoiceId }: { invoiceId: string }) {
  const t = useTranslations("billing.invoices");
  const totalsT = useTranslations("billing.totals");
  const query = useInvoicesRetrieve(invoiceId);
  const kinds = useTranslations("billing.creditNoteKinds");
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const invoice = query.data?.data;
  if (!invoice) return <EmptyState title={t("notFound")} />;
  const intra = invoice.supply_type === "INTRA";
  return (
    <>
      <Link
        href="/manage/invoices"
        className="text-muted-foreground mb-4 inline-flex min-h-10 items-center gap-1 text-sm hover:underline max-md:min-h-11"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("back")}
      </Link>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
              {t("heading", { number: invoice.number })}
              <StatusBadge status={invoice.payment_status} />
            </h1>
            <p className="text-muted-foreground flex flex-wrap items-center gap-x-3 text-sm">
              <Link
                href={`/manage/retailers/${invoice.retailer.id}`}
                className="inline-flex min-h-10 items-center hover:underline max-md:min-h-11"
              >
                {invoice.retailer.shop_name}
              </Link>
              <DateText value={invoice.invoice_date} />
              <Link
                href={`/manage/orders/${invoice.order.id}`}
                className="inline-flex min-h-10 items-center hover:underline max-md:min-h-11"
              >
                {t("forOrder", { number: invoice.order.number })}
              </Link>
            </p>
            <p className="text-sm">
              {t("dueOn")} <DueText due={invoice.due_date} daysOverdue={invoice.days_overdue} />
            </p>
          </div>
          <InvoiceActions invoice={invoice} />
        </div>
        {invoice.rate_differs_from_order ? (
          <p className="bg-warning/15 flex gap-2 rounded-xl p-3 text-sm">
            <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
            {t("rateDiffers")}
          </p>
        ) : null}
        {invoice.pdf_status === "FAILED" ? (
          <p className="bg-destructive/10 rounded-xl p-3 text-sm">{t("pdfFailed")}</p>
        ) : null}
        <div className="grid gap-6 xl:grid-cols-[1fr_24rem] xl:items-start">
          <div className="space-y-6">
            <section className="space-y-2" aria-labelledby="invoice-lines">
              <h2 id="invoice-lines" className="font-semibold">
                {t("items")}
              </h2>
              <ul className="divide-y rounded-xl border">
                {invoice.lines.map((line) => (
                  <li key={line.id} className="space-y-1 p-3 text-sm">
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block font-medium">{line.description}</span>
                        <span className="text-muted-foreground text-xs">
                          {t("lineMeta", {
                            code: line.product_code,
                            hsn: line.hsn_code,
                            qty: formatQty(line.quantity),
                            unit: line.unit_code,
                          })}
                          {" × "}
                          <MoneyText value={line.unit_price} />
                        </span>
                      </span>
                      <MoneyText value={line.line_total} className="font-medium" />
                    </div>
                    <p className="text-muted-foreground text-xs">
                      {line.discount_amount !== "0.00" ? (
                        <>
                          {t("discount")} <MoneyText value={line.discount_amount} />
                          {" · "}
                        </>
                      ) : null}
                      {t("taxableValue")} <MoneyText value={line.taxable_value} />
                      {" · "}
                      <LineTax line={line} intra={intra} />
                      {line.rate_differs_from_order ? (
                        <span className="text-warning-strong">
                          {" · "}
                          {t("orderedAt", { rate: formatQty(line.order_rate) })}
                        </span>
                      ) : null}
                      {line.credited_quantity !== "0.000" ? (
                        <span>
                          {" · "}
                          {t("credited", { qty: formatQty(line.credited_quantity) })}
                        </span>
                      ) : null}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
            {invoice.credit_notes.length ? (
              <section className="space-y-2" aria-labelledby="invoice-credit-notes">
                <h2 id="invoice-credit-notes" className="font-semibold">
                  {t("creditNotes")}
                </h2>
                <ul className="divide-y rounded-xl border text-sm">
                  {invoice.credit_notes.map((note) => (
                    <li key={note.id} className="flex flex-wrap justify-between gap-2 p-3">
                      <span>
                        <Link
                          href={`/manage/invoices/credit-notes/${note.id}`}
                          className="font-medium hover:underline"
                        >
                          {note.number}
                        </Link>
                        <span className="text-muted-foreground block text-xs">
                          {kinds(note.kind)}
                          {note.issued_automatically ? ` · ${t("automaticNote")}` : ""}
                        </span>
                      </span>
                      <MoneyText value={note.grand_total} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <section className="space-y-2" aria-labelledby="invoice-applied">
              <h2 id="invoice-applied" className="font-semibold">
                {t("applied")}
              </h2>
              <AppliedList rows={invoice.applied} />
            </section>
          </div>
          <aside className="space-y-4 rounded-xl border p-4">
            <h2 className="font-semibold">{t("totals")}</h2>
            <DocumentTotals
              totals={invoice.totals}
              intra={intra}
              totalLabel={totalsT("invoiceTotal")}
              extra={[
                { label: totalsT("paid"), value: invoice.amount_paid },
                { label: totalsT("credited"), value: invoice.amount_credited },
                { label: totalsT("balanceDue"), value: invoice.balance_due, strong: true },
              ]}
            />
            <p className="text-muted-foreground text-xs">{invoice.amount_in_words}</p>
            <p className="text-muted-foreground text-xs">
              {t("placeOfSupply", {
                place: `${invoice.place_of_supply.name} (${invoice.place_of_supply.code})`,
              })}
            </p>
          </aside>
        </div>
      </div>
    </>
  );
}
