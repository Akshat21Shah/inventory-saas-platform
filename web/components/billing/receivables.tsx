"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarClock, HandCoins, IndianRupee, Store, Wallet } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { ActionDialog } from "@/components/orders/action-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { KpiCard } from "@/components/shared/kpi-card";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ledgerAdjustmentsCreate,
  useReceivablesAgeing,
  useReceivablesSummary,
  useRetailersLedger,
} from "@/lib/api/generated/endpoints/receivables/receivables";
import {
  LedgerAdjustmentKindEnum,
  type ReceivableRow,
  type ReceivablesAgeingBasis,
} from "@/lib/api/generated/model";
import { formatDate, formatMoney } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

import { PaymentsNav } from "./billing-nav";
import { todayInIndia } from "./shop-picker";

const BUCKETS = ["d0_30", "d31_60", "d61_90", "d90_plus"] as const;

/** Owed, overdue and collections to hand over, for the dashboard and receivables page. */
export function ReceivablesCards({ linked = false }: { linked?: boolean }) {
  const t = useTranslations("billing.receivables");
  const { can } = useAuth();
  const summary = useReceivablesSummary({ query: { enabled: can("ledger.view") } }).data?.data;
  if (!summary) return null;
  const cards = [
    {
      key: "owed",
      href: "/manage/receivables",
      label: t("owed"),
      value: summary.owed,
      icon: IndianRupee,
    },
    {
      key: "overdue",
      href: "/manage/receivables",
      label: t("overdueShops", { count: summary.shops_overdue }),
      value: summary.overdue,
      icon: Store,
    },
    {
      key: "week",
      href: "/manage/receivables",
      label: t("dueThisWeek"),
      value: summary.due_this_week,
      icon: CalendarClock,
    },
    summary.collections_pending_handover !== null
      ? {
          key: "salesmen",
          href: "/manage/payments/handover",
          label: t("withSalesmen"),
          value: summary.collections_pending_handover,
          icon: HandCoins,
        }
      : {
          key: "credit",
          href: "/manage/receivables",
          label: t("unusedCredit"),
          value: summary.unapplied_credit,
          icon: Wallet,
        },
  ];
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <li key={card.key}>
          {linked ? (
            <Link href={card.href} className="block rounded-xl focus-visible:ring-2">
              <KpiCard label={card.label} value={formatMoney(card.value)} icon={card.icon} />
            </Link>
          ) : (
            <KpiCard label={card.label} value={formatMoney(card.value)} icon={card.icon} />
          )}
        </li>
      ))}
    </ul>
  );
}

/** Who owes what, aged by invoice date or days past due (⚙ receivables.ageing_basis). */
export function ReceivablesPage() {
  const t = useTranslations("billing.receivables");
  const [search, setSearch] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [basis, setBasis] = useState<ReceivablesAgeingBasis | undefined>(undefined);
  const [page, setPage] = useState(1);
  const term = useDebounced(search.trim(), 300);
  const query = useReceivablesAgeing({
    search: term || undefined,
    overdue: overdue || undefined,
    basis,
    page,
    page_size: 50,
  });
  const data = query.data?.data;
  const byDue = data?.basis === "DUE_DATE";
  const bucketIds = byDue ? (["not_due", ...BUCKETS] as const) : BUCKETS;
  const columns: DataTableColumn<ReceivableRow>[] = [
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <Link
          href={`/manage/retailers/${row.original.retailer.id}/ledger`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.retailer.shop_name}
        </Link>
      ),
    },
    {
      id: "owed",
      header: t("owedColumn"),
      cell: ({ row }) => <MoneyText value={row.original.owed} />,
    },
    {
      id: "overdue",
      header: t("overdue"),
      cell: ({ row }) => (
        <span className="space-y-0.5">
          <MoneyText value={row.original.overdue} />
          {row.original.days_overdue > 0 ? (
            <span className="text-destructive block text-xs">
              {t("oldest", { days: row.original.days_overdue })}
            </span>
          ) : null}
        </span>
      ),
    },
    ...bucketIds.map((bucket): DataTableColumn<ReceivableRow> => ({
      id: bucket,
      header: t(`bucket.${bucket}`),
      cell: ({ row }) => <MoneyText value={row.original.buckets[bucket]} />,
    })),
    {
      id: "credit",
      header: t("credit"),
      cell: ({ row }) => <MoneyText value={row.original.unapplied_credit} />,
    },
    {
      id: "lastPayment",
      header: t("lastPayment"),
      cell: ({ row }) =>
        row.original.last_payment_date ? (
          <span className="space-y-0.5">
            <DateText value={row.original.last_payment_date} />
            <span className="text-muted-foreground block text-xs">
              <MoneyText value={row.original.last_payment_amount ?? "0.00"} />
            </span>
          </span>
        ) : (
          "—"
        ),
    },
    {
      id: "salesperson",
      header: t("salesperson"),
      cell: ({ row }) => row.original.salesperson_name || "—",
    },
  ];
  const pages = data ? Math.max(1, Math.ceil(data.count / data.page_size)) : 1;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PaymentsNav />
      <div className="mb-6">
        <ReceivablesCards />
      </div>
      {data ? (
        <div
          role="group"
          aria-label={t("basis")}
          className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0"
        >
          {(["INVOICE_DATE", "DUE_DATE"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={data.basis === value}
              onClick={() => {
                setBasis(value);
                setPage(1);
              }}
              className={cn(
                "flex min-h-11 shrink-0 items-center rounded-full border px-4 text-sm md:min-h-10",
                data.basis === value
                  ? "border-brand-200 bg-brand-50 font-medium"
                  : "hover:bg-muted",
              )}
            >
              {t(`by.${value}`)}
            </button>
          ))}
        </div>
      ) : null}
      {data ? (
        <dl className="mb-4 grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {bucketIds.map((bucket) => (
            <div key={bucket}>
              <dt className="text-muted-foreground text-xs">{t(`bucket.${bucket}`)}</dt>
              <dd className="font-semibold">
                <MoneyText value={data.totals.buckets[bucket]} />
              </dd>
            </div>
          ))}
          <div>
            <dt className="text-muted-foreground text-xs">{t("net")}</dt>
            <dd className="font-semibold">
              <MoneyText value={data.totals.net} />
            </dd>
          </div>
        </dl>
      ) : null}
      <DataTable
        columns={columns}
        data={data?.results ?? []}
        getRowId={(row) => row.retailer.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["owed", "overdue", "credit", ...bucketIds]}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          shop: "title",
          owed: "primary",
          overdue: "primary",
          credit: "primary",
          lastPayment: "secondary",
          salesperson: "secondary",
          ...Object.fromEntries(bucketIds.map((b) => [b, "secondary" as const])),
        }}
        toolbar={
          <FilterBar
            active={[term, overdue].filter(Boolean).length}
            onClear={() => {
              setSearch("");
              setOverdue(false);
              setPage(1);
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder={t("searchPlaceholder")}
                aria-label={t("search")}
                className="min-h-10"
              />
            }
            filters={
              <label className="flex min-h-10 items-center gap-2 text-sm max-md:min-h-11">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={overdue}
                  onChange={(e) => {
                    setOverdue(e.target.checked);
                    setPage(1);
                  }}
                />
                {t("overdueOnly")}
              </label>
            }
          />
        }
      />
      {pages > 1 ? (
        <nav aria-label={t("pages")} className="mt-4 flex items-center justify-end gap-2 text-sm">
          <Button
            variant="outline"
            className="min-h-10"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t("previous")}
          </Button>
          <span>{t("pageOf", { page, pages })}</span>
          <Button
            variant="outline"
            className="min-h-10"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            {t("next")}
          </Button>
        </nav>
      ) : null}
    </>
  );
}

function AdjustmentDialog({ retailerId }: { retailerId: string }) {
  const t = useTranslations("billing.statement.adjust");
  const kinds = useTranslations("billing.adjustmentKinds");
  const client = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const [kind, setKind] = useState<string>("DEBIT");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayInIndia);
  const [due, setDue] = useState("");
  const [bill, setBill] = useState("");
  const [narration, setNarration] = useState("");
  const debit = kind === "DEBIT" || kind === "OPENING_DEBIT";
  return (
    <ActionDialog
      trigger={
        <Button variant="outline" className="min-h-10">
          {t("open")}
        </Button>
      }
      title={t("title")}
      description={t("body")}
      confirmLabel={t("save")}
      disabled={!amount.trim() || !narration.trim()}
      onSubmit={async () => {
        await ledgerAdjustmentsCreate(
          {
            retailer: retailerId,
            kind: kind as LedgerAdjustmentKindEnum,
            amount: amount.trim(),
            date,
            due_date: debit && due ? due : null,
            bill_number: kind === "OPENING_DEBIT" ? bill : "",
            narration,
          },
          idempotent(key),
        );
        setKey(newIdempotencyKey());
        setAmount("");
        setNarration("");
        void client.invalidateQueries();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label={t("kind")} className="sm:col-span-2">
          <FormSelect
            value={kind}
            onValueChange={setKind}
            options={Object.values(LedgerAdjustmentKindEnum).map((v) => ({
              value: v,
              label: kinds(v),
            }))}
          />
        </FormField>
        <FormField label={t("amount")} required>
          <Input
            inputMode="decimal"
            className="min-h-10"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </FormField>
        <FormField label={kind === "OPENING_DEBIT" ? t("billDate") : t("date")} required>
          <Input
            type="date"
            className="min-h-10"
            value={date}
            max={todayInIndia()}
            onChange={(e) => setDate(e.target.value)}
          />
        </FormField>
        {debit ? (
          <FormField label={t("dueDate")} hint={t("dueHint")}>
            <Input
              type="date"
              className="min-h-10"
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </FormField>
        ) : null}
        {kind === "OPENING_DEBIT" ? (
          <FormField label={t("billNumber")}>
            <Input className="min-h-10" value={bill} onChange={(e) => setBill(e.target.value)} />
          </FormField>
        ) : null}
        <FormField label={t("narration")} required className="sm:col-span-2">
          <Input
            className="min-h-10"
            value={narration}
            onChange={(e) => setNarration(e.target.value)}
          />
        </FormField>
      </div>
    </ActionDialog>
  );
}

/** A shop's account: position, statement with running balance, and money actions. */
export function RetailerLedgerPage({ retailerId }: { retailerId: string }) {
  const t = useTranslations("billing.statement");
  const entries = useTranslations("billing.entryTypes");
  const { can } = useAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const query = useRetailersLedger(retailerId, {
    date_from: from || undefined,
    date_to: to || undefined,
  });
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const statement = query.data?.data;
  if (!statement) return <EmptyState title={t("notFound")} />;
  const p = statement.position;
  const link = (line: (typeof statement.lines)[number]) =>
    line.reference_type === "INVOICE"
      ? `/manage/invoices/${line.reference_id}`
      : line.reference_type === "CREDIT_NOTE"
        ? `/manage/invoices/credit-notes/${line.reference_id}`
        : line.reference_type === "PAYMENT"
          ? `/manage/payments/${line.reference_id}`
          : line.reference_type === "REFUND"
            ? `/manage/payments/refunds/${line.reference_id}`
            : null;
  return (
    <>
      <Link
        href={`/manage/retailers/${retailerId}`}
        className="text-muted-foreground mb-4 inline-flex min-h-10 items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {statement.retailer.shop_name}
      </Link>
      <PageHeader
        title={t("title", { shop: statement.retailer.shop_name })}
        description={t("description")}
        actions={
          <>
            {can("payments.record") || can("payments.collect") ? (
              <Button asChild className="min-h-10">
                <Link href={`/manage/payments/new?retailer=${retailerId}`}>
                  {t("recordPayment")}
                </Link>
              </Button>
            ) : null}
            {can("payments.record") && p.unapplied_credit !== "0.00" ? (
              <Button asChild variant="outline" className="min-h-10">
                <Link href={`/manage/payments/refunds/new?retailer=${retailerId}`}>
                  {t("refund")}
                </Link>
              </Button>
            ) : null}
            {can("ledger.adjust") ? <AdjustmentDialog retailerId={retailerId} /> : null}
          </>
        }
      />
      <dl className="mb-4 grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm sm:grid-cols-5">
        {[
          ["owed", p.owed],
          ["overdue", p.overdue],
          ["credit", p.unapplied_credit],
          ["net", p.balance],
        ].map(([key, value]) => (
          <div key={key}>
            <dt className="text-muted-foreground text-xs">{t(`position.${key}`)}</dt>
            <dd className="font-semibold">
              <MoneyText value={value!} />
            </dd>
          </div>
        ))}
        <div>
          <dt className="text-muted-foreground text-xs">{t("position.limit")}</dt>
          <dd className="font-semibold">
            {statement.credit_limit === null ? (
              t("noLimit")
            ) : (
              <MoneyText value={statement.credit_limit} />
            )}
          </dd>
        </div>
      </dl>
      {p.days_overdue > 0 ? (
        <p className="text-destructive mb-4 text-sm">{t("oldest", { days: p.days_overdue })}</p>
      ) : null}
      {statement.credit_held_while_advances_off ? (
        <p className="bg-info/10 mb-4 rounded-xl p-3 text-sm">
          {t("heldAsCredit", { amount: formatMoney(statement.credit_held_while_advances_off) })}
        </p>
      ) : null}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          {t("from")}
          <Input
            type="date"
            value={from || statement.date_from}
            onChange={(e) => setFrom(e.target.value)}
            className="min-h-10"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          {t("to")}
          <Input
            type="date"
            value={to || statement.date_to}
            onChange={(e) => setTo(e.target.value)}
            className="min-h-10"
          />
        </label>
      </div>
      <section aria-labelledby="statement-lines" className="space-y-2">
        <h2 id="statement-lines" className="sr-only">
          {t("entries")}
        </h2>
        <div className="flex justify-between rounded-t-xl border px-3 py-2 text-sm">
          <span>{t("opening", { date: formatDate(statement.date_from) })}</span>
          <MoneyText value={statement.opening_balance} className="font-medium" />
        </div>
        {statement.lines.length === 0 ? (
          <EmptyState title={t("noEntries")} />
        ) : (
          <ul className="divide-y border-x text-sm">
            {statement.lines.map((line) => {
              const href = link(line);
              return (
                <li
                  key={line.id}
                  className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 p-3 md:grid-cols-[7rem_1fr_7rem_7rem_7rem]"
                >
                  <span className="text-muted-foreground text-xs md:text-sm">
                    <DateText value={line.entry_date} />
                  </span>
                  <span className="min-w-0 max-md:col-span-2 max-md:row-start-2">
                    {href ? (
                      <Link href={href} className="font-medium hover:underline">
                        {entries(line.entry_type)} {line.reference_number}
                      </Link>
                    ) : (
                      <span className="font-medium">
                        {line.reference_number || entries(line.entry_type)}
                      </span>
                    )}
                    {line.narration ? (
                      <span className="text-muted-foreground block text-xs">{line.narration}</span>
                    ) : null}
                  </span>
                  <span className="text-right max-md:col-start-2 max-md:row-start-1">
                    {line.debit !== "0.00" ? (
                      <MoneyText value={line.debit} />
                    ) : (
                      <span className="text-success-strong">
                        −<MoneyText value={line.credit} />
                      </span>
                    )}
                  </span>
                  <span className="hidden md:block" />
                  <span className="text-muted-foreground text-right text-xs max-md:col-span-2 md:text-sm">
                    {t("balance")} <MoneyText value={line.balance} />
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex justify-between rounded-b-xl border px-3 py-2 text-sm font-semibold">
          <span>{t("closing", { date: formatDate(statement.date_to) })}</span>
          <MoneyText value={statement.closing_balance} />
        </div>
      </section>
    </>
  );
}
