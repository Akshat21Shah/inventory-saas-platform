"use client";

import { DocumentLinksCard } from "@/components/notifications/manage/cards";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { EInvoicePanel, einvoiceMoving } from "@/components/compliance/einvoice";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton, TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FreeLineLabel } from "@/components/shop/free-goods";
import {
  creditNotesCreate,
  creditNotesPdf,
  creditNotesRegeneratePdf,
  getCreditNotesRetrieveQueryKey,
  useCreditNotesList,
  useCreditNotesRetrieve,
  useInvoicesList,
  useInvoicesRetrieve,
} from "@/lib/api/generated/endpoints/billing/billing";
import {
  CreditNoteKindEnum,
  DispositionEnum,
  ReturnReasonEnum,
  type CreditNoteCreateKindEnum,
  type CreditNoteRow,
  type CreditNotesListKind,
  type InvoiceDetail,
} from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { fromMilli, toMilli } from "@/lib/qty";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { useListSearch } from "@/lib/list-search";

import { BillingNav } from "./billing-nav";
import { DocumentButton } from "./document-button";
import { DocumentTotals } from "./invoices";
import { UsedForList } from "./used-for";

const ALL = "all";

/** "Issued automatically (short supply / cancellation)" next to a credit note (ADR-046). */
export function AutomaticMark({ automatic }: { automatic?: boolean }) {
  const t = useTranslations("billing.creditNotes");
  if (!automatic) return null;
  return (
    <span className="bg-info/12 text-info-strong rounded-full px-2 py-0.5 text-xs font-medium">
      {t("automatic")}
    </span>
  );
}

export function CreditNotesPage() {
  const t = useTranslations("billing.creditNotes");
  const kinds = useTranslations("billing.creditNoteKinds");
  const { can } = useAuth();
  const cursor = useCursor();
  const [search, setSearch] = useListSearch();
  const [kind, setKind] = useState<string>(ALL);
  const [source, setSource] = useState<string>(ALL);
  const term = useDebounced(search.trim(), 300);
  const query = useCreditNotesList({
    cursor: cursor.cursor,
    search: term || undefined,
    kind: kind === ALL ? undefined : (kind as CreditNotesListKind),
    automatic: source === ALL ? undefined : source === "automatic",
  });
  const page = query.data?.data;
  const columns: DataTableColumn<CreditNoteRow>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/invoices/credit-notes/${row.original.id}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.retailer.shop_name },
    {
      id: "invoice",
      header: t("invoice"),
      cell: ({ row }) => (
        <Link href={`/manage/invoices/${row.original.invoice.id}`} className="hover:underline">
          {row.original.invoice.number}
        </Link>
      ),
    },
    {
      id: "kind",
      header: t("kind"),
      cell: ({ row }) => (
        <span className="flex flex-wrap items-center gap-1.5">
          {kinds(row.original.kind)}
          <AutomaticMark automatic={row.original.issued_automatically} />
        </span>
      ),
    },
    {
      id: "date",
      header: t("date"),
      cell: ({ row }) => <DateText value={row.original.note_date} />,
    },
    {
      id: "total",
      header: t("total"),
      cell: ({ row }) => <MoneyText value={row.original.grand_total} />,
    },
    {
      id: "left",
      header: t("creditLeft"),
      cell: ({ row }) => <MoneyText value={row.original.unapplied_amount} />,
    },
  ];
  const active = [term, kind !== ALL, source !== ALL].filter(Boolean).length;
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("invoices.manage") ? (
            <Button asChild className="min-h-10 gap-2">
              <Link href="/manage/invoices/credit-notes/new">
                <Plus aria-hidden className="size-4" />
                {t("new")}
              </Link>
            </Button>
          ) : null
        }
      />
      <BillingNav />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["total", "left"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          number: "title",
          shop: "primary",
          kind: "primary",
          total: "primary",
          invoice: "secondary",
          date: "secondary",
          left: "secondary",
        }}
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              setSearch("");
              setKind(ALL);
              setSource(ALL);
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
                  label={t("kind")}
                  value={kind}
                  onChange={(value) => {
                    setKind(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allKinds") },
                    ...Object.values(CreditNoteKindEnum).map((value) => ({
                      value,
                      label: kinds(value),
                    })),
                  ]}
                />
                <FilterSelect
                  label={t("source")}
                  value={source}
                  onChange={(value) => {
                    setSource(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allSources") },
                    { value: "automatic", label: t("automatic") },
                    { value: "staff", label: t("byStaff") },
                  ]}
                />
              </>
            }
          />
        }
      />
    </>
  );
}

export function CreditNoteDetailPage({ noteId }: { noteId: string }) {
  const t = useTranslations("billing.creditNotes");
  const kinds = useTranslations("billing.creditNoteKinds");
  const reasons = useTranslations("billing.returnReasons");
  const dispositions = useTranslations("billing.dispositions");
  const totalsT = useTranslations("billing.totals");
  const { can } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useCreditNotesRetrieve(noteId, {
    query: {
      refetchInterval: (q) => (einvoiceMoving(q.state.data?.data.einvoice) ? 3000 : false),
    },
  });
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const note = query.data?.data;
  if (!note) return <EmptyState title={t("notFound")} />;
  const intra = note.supply_type === "INTRA";
  return (
    <>
      <Link
        href="/manage/invoices/credit-notes"
        className="text-muted-foreground mb-4 inline-flex min-h-10 items-center gap-1 text-sm hover:underline max-md:min-h-11 max-md:min-w-11"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("back")}
      </Link>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
              {t("heading", { number: note.number })}
              <AutomaticMark automatic={note.issued_automatically} />
            </h1>
            <p className="text-muted-foreground text-sm">
              {note.retailer.shop_name}
              {" · "}
              <DateText value={note.note_date} />
              {" · "}
              <Link href={`/manage/invoices/${note.invoice.id}`} className="hover:underline">
                {t("againstInvoice", { number: note.invoice.number })}
              </Link>
            </p>
            <p className="text-sm">
              {kinds(note.kind)}
              {note.return_reason ? `: ${reasons(note.return_reason)}` : ""}
              {note.reason_note ? ` · ${note.reason_note}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <DocumentButton fetchLink={() => creditNotesPdf(note.id)}>
              {t("download")}
            </DocumentButton>
            {note.pdf_status === "FAILED" && can("invoices.manage") ? (
              <Button
                variant="outline"
                className="min-h-10 gap-2"
                onClick={async () => {
                  try {
                    await creditNotesRegeneratePdf(note.id);
                    toast.success(t("regenerating"));
                    void client.invalidateQueries({
                      queryKey: getCreditNotesRetrieveQueryKey(note.id),
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
          </div>
        </div>
        <div className="grid gap-6 xl:grid-cols-[1fr_24rem] xl:items-start">
          <div className="space-y-6">
            <section className="space-y-2" aria-labelledby="note-lines">
              <h2 id="note-lines" className="font-semibold">
                {t("items")}
              </h2>
              <ul className="divide-y rounded-xl border">
                {note.lines.map((line) => (
                  <li
                    key={line.line_no}
                    className="flex flex-wrap justify-between gap-2 p-3 text-sm"
                  >
                    <span className="min-w-0">
                      <span className="block font-medium">{line.description}</span>
                      {line.is_free ? <FreeLineLabel scheme={line.scheme_name} /> : null}
                      <span className="text-muted-foreground block text-xs">
                        {line.quantity !== "0.000"
                          ? t("lineQty", { qty: formatQty(line.quantity), unit: line.unit_code })
                          : t("valueOnly")}
                        {line.disposition ? ` · ${dispositions(line.disposition)}` : ""}
                        {" · "}
                        {t("taxable")} <MoneyText value={line.taxable_value} />
                      </span>
                    </span>
                    <MoneyText value={line.line_total} className="font-medium" />
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-2" aria-labelledby="note-used">
              <h2 id="note-used" className="font-semibold">
                {t("usedFor")}
              </h2>
              <UsedForList rows={note.used_for} />
            </section>
            <DocumentLinksCard kind="CREDIT_NOTE" objectId={note.id} />
          </div>
          <div className="space-y-4">
            <aside className="space-y-4 rounded-xl border p-4">
              <h2 className="font-semibold">{t("totals")}</h2>
              <DocumentTotals
                totals={note.totals}
                intra={intra}
                totalLabel={totalsT("creditTotal")}
                extra={[
                  { label: totalsT("againstInvoice"), value: note.applied_to_invoice },
                  { label: totalsT("creditLeft"), value: note.unapplied_amount, strong: true },
                ]}
              />
              <p className="text-muted-foreground text-xs">{note.amount_in_words}</p>
            </aside>
            <EInvoicePanel
              kind="credit_note"
              documentId={note.id}
              summary={note.einvoice}
              registeredBuyer={Boolean((note.buyer as { gstin?: string } | null)?.gstin)}
              onChanged={() =>
                void client.invalidateQueries({ queryKey: getCreditNotesRetrieveQueryKey(note.id) })
              }
            />
          </div>
        </div>
      </div>
    </>
  );
}

function InvoicePicker() {
  const t = useTranslations("billing.creditNotes.form");
  const router = useRouter();
  const [search, setSearch] = useState("");
  const term = useDebounced(search.trim(), 300);
  const query = useInvoicesList({ search: term || undefined, page_size: 10 });
  const rows = query.data?.data.results ?? [];
  return (
    <section className="max-w-2xl space-y-3" aria-labelledby="pick-invoice">
      <h2 id="pick-invoice" className="font-semibold">
        {t("pickInvoice")}
      </h2>
      <Input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={t("invoiceSearch")}
        aria-label={t("invoiceSearch")}
        className="min-h-10"
      />
      {query.isLoading ? (
        <TableSkeleton rows={3} columns={2} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("noInvoices")} />
      ) : (
        <ul className="divide-y rounded-xl border">
          {rows.map((invoice) => (
            <li key={invoice.id}>
              <button
                type="button"
                className="hover:bg-muted flex min-h-11 w-full flex-wrap items-center justify-between gap-2 p-3 text-left text-sm"
                onClick={() =>
                  router.replace(`/manage/invoices/credit-notes/new?invoice=${invoice.id}`)
                }
              >
                <span>
                  <span className="block font-medium">{invoice.number}</span>
                  <span className="text-muted-foreground text-xs">
                    {invoice.retailer.shop_name} · <DateText value={invoice.invoice_date} />
                  </span>
                </span>
                <MoneyText value={invoice.grand_total} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface LineInput {
  quantity: string;
  disposition: string;
  taxable: string;
}

function CreditNoteForm({ invoice }: { invoice: InvoiceDetail }) {
  const t = useTranslations("billing.creditNotes.form");
  const reasons = useTranslations("billing.returnReasons");
  const dispositions = useTranslations("billing.dispositions");
  const router = useRouter();
  const { message, fields } = useErrorText();
  const [key] = useState(newIdempotencyKey);
  const [kind, setKind] = useState<CreditNoteCreateKindEnum>("RETURN");
  const [reason, setReason] = useState<string>("DAMAGED");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Record<string, LineInput>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const set = (id: string, patch: Partial<LineInput>) =>
    setLines((all) => ({
      ...all,
      [id]: { quantity: "", disposition: "RETURN_TO_STOCK", taxable: "", ...all[id], ...patch },
    }));
  const chosen = Object.entries(lines).filter(([, v]) =>
    kind === "RETURN" ? v.quantity.trim() !== "" : v.taxable.trim() !== "",
  );

  async function submit() {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      const response = await creditNotesCreate(
        {
          invoice: invoice.id,
          kind,
          reason:
            kind === "RETURN"
              ? (reason as (typeof ReturnReasonEnum)[keyof typeof ReturnReasonEnum])
              : "",
          note,
          lines: chosen.map(([id, v]) =>
            kind === "RETURN"
              ? {
                  invoice_line: id,
                  quantity: v.quantity,
                  disposition:
                    v.disposition as (typeof DispositionEnum)[keyof typeof DispositionEnum],
                }
              : { invoice_line: id, taxable_value: v.taxable },
          ),
        },
        idempotent(key),
      );
      toast.success(t("created", { number: response.data.number }));
      router.push(`/manage/invoices/credit-notes/${response.data.id}`);
    } catch (thrown) {
      setError(message(thrown));
      if (thrown instanceof ApiError) setFieldErrors(fields(thrown));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="max-w-3xl space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <p className="text-sm">
        {t("forInvoice", { number: invoice.number, shop: invoice.retailer.shop_name })}
      </p>
      <fieldset className="space-y-2">
        <legend className="font-semibold">{t("what")}</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup">
          {(["RETURN", "PRICE_ADJUSTMENT"] as const).map((value) => (
            <label
              key={value}
              className={cn(
                "flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-4 text-sm",
                kind === value && "border-brand-300 bg-brand-50",
              )}
            >
              <input
                type="radio"
                name="kind"
                value={value}
                checked={kind === value}
                onChange={() => setKind(value)}
              />
              {t(value === "RETURN" ? "return" : "priceAdjustment")}
            </label>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {t(kind === "RETURN" ? "returnHint" : "priceHint")}
        </p>
      </fieldset>
      <section className="space-y-2" aria-labelledby="credit-lines">
        <h2 id="credit-lines" className="font-semibold">
          {t("items")}
        </h2>
        <ul className="divide-y rounded-xl border">
          {invoice.lines.map((line) => {
            const left = fromMilli(
              (toMilli(line.quantity) ?? 0) - (toMilli(line.credited_quantity) ?? 0),
            );
            const value = lines[line.id];
            return (
              <li key={line.id} className="space-y-2 p-3">
                <div className="text-sm">
                  <span className="block font-medium">{line.description}</span>
                  {line.is_free ? <FreeLineLabel scheme={line.scheme_name} /> : null}
                  <span className="text-muted-foreground block text-xs">
                    {t("invoiced", {
                      qty: formatQty(line.quantity),
                      unit: line.unit_code,
                      left: formatQty(left),
                    })}
                    {" · "}
                    {t("taxableValue")} <MoneyText value={line.taxable_value} />
                  </span>
                </div>
                {kind === "RETURN" ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <FormField label={t("quantityBack")}>
                      <Input
                        inputMode="decimal"
                        className="min-h-10"
                        value={value?.quantity ?? ""}
                        onChange={(e) => set(line.id, { quantity: e.target.value })}
                        placeholder={t("upTo", { qty: formatQty(left) })}
                      />
                    </FormField>
                    <FormField label={t("disposition")}>
                      <FormSelect
                        value={value?.disposition ?? "RETURN_TO_STOCK"}
                        onValueChange={(v) => set(line.id, { disposition: v })}
                        options={Object.values(DispositionEnum).map((v) => ({
                          value: v,
                          label: dispositions(v),
                        }))}
                      />
                    </FormField>
                  </div>
                ) : (
                  <FormField label={t("taxableToCredit")} hint={t("taxableHint")}>
                    <Input
                      inputMode="decimal"
                      className="min-h-10 sm:w-48"
                      value={value?.taxable ?? ""}
                      onChange={(e) => set(line.id, { taxable: e.target.value })}
                    />
                  </FormField>
                )}
              </li>
            );
          })}
        </ul>
        {fieldErrors.lines ? <p className="text-destructive text-sm">{fieldErrors.lines}</p> : null}
      </section>
      {kind === "RETURN" ? (
        <FormField label={t("reason")} required error={fieldErrors.reason}>
          <FormSelect
            value={reason}
            onValueChange={setReason}
            options={Object.values(ReturnReasonEnum).map((v) => ({ value: v, label: reasons(v) }))}
          />
        </FormField>
      ) : null}
      <FormField
        label={t("note")}
        required={kind === "PRICE_ADJUSTMENT" || reason === "OTHER"}
        hint={t("noteHint")}
        error={fieldErrors.note}
      >
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </FormField>
      {error ? (
        <p role="alert" className="bg-destructive/10 text-destructive rounded-xl p-3 text-sm">
          {error}
        </p>
      ) : null}
      <FormActions>
        <Button variant="outline" type="button" className="min-h-10" onClick={() => router.back()}>
          {t("cancel")}
        </Button>
        <Button type="submit" className="min-h-10" disabled={busy || chosen.length === 0}>
          {t("issue")}
        </Button>
      </FormActions>
    </form>
  );
}

/** Issue a credit note: a return (quantities and what happened to the goods) or a value-only
 * price adjustment, against one invoice. The server works out every amount. */
export function NewCreditNotePage() {
  const t = useTranslations("billing.creditNotes.form");
  const params = useSearchParams();
  const invoiceId = params.get("invoice") ?? "";
  const query = useInvoicesRetrieve(invoiceId, { query: { enabled: Boolean(invoiceId) } });
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <BillingNav />
      {!invoiceId ? (
        <InvoicePicker />
      ) : query.isLoading ? (
        <PageSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data?.data ? (
        <CreditNoteForm invoice={query.data.data} />
      ) : null}
    </>
  );
}
