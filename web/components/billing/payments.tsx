"use client";

import { DocumentLinksCard } from "@/components/notifications/manage/cards";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, HandCoins, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { ActionDialog } from "@/components/orders/action-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  paymentAllocationsReverse,
  paymentReview,
  paymentsAllocate,
  paymentsBounce,
  paymentsClear,
  paymentsCollect,
  paymentsHandover,
  paymentsReceipt,
  paymentsRecord,
  paymentsReverse,
  useReportsCollectionsPendingHandover,
  usePaymentsList,
  usePaymentsRetrieve,
} from "@/lib/api/generated/endpoints/payments/payments";
import { useRetailersDues } from "@/lib/api/generated/endpoints/receivables/receivables";
import { useRetailersRetrieve } from "@/lib/api/generated/endpoints/retailers/retailers";
import {
  HandoverStatusEnum,
  ManualPaymentModeEnum,
  PaymentModeEnum,
  PaymentStatusEnum,
  type Due,
  type DueAmountRequest,
  type Dues,
  type PaymentDetail,
  type PaymentRow,
  type PaymentsListHandoverStatus,
  type PaymentsListMode,
  type PaymentsListStatus,
  type StaffPaymentRow,
  type UsedFor,
} from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useDebounced } from "@/lib/use-debounced";
import { useListSearch } from "@/lib/list-search";

import { PaymentsNav } from "./billing-nav";
import { DocumentButton } from "./document-button";
import { ShopPicker, todayInIndia } from "./shop-picker";
import { UsedForList } from "./used-for";

const ALL = "all";

export interface ShopChoice {
  id: string;
  shop_name: string;
  code: string;
}

function refreshMoney(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({
    predicate: (q) => {
      const key = String(q.queryKey[0] ?? "");
      return (
        key.startsWith("/api/v1/payments") ||
        key.startsWith("/api/v1/refunds") ||
        key.startsWith("/api/v1/invoices") ||
        key.startsWith("/api/v1/receivables") ||
        key.startsWith("/api/v1/retailers") ||
        key.startsWith("/api/v1/reports")
      );
    },
  });
}

/** The notices staff must see on a payment (ADR-047). */
function PaymentNotices({ payment }: { payment: PaymentRow }) {
  const t = useTranslations("billing.payments");
  return (
    <>
      {payment.dated_in_previous_financial_year ? (
        <p className="bg-warning/15 flex gap-2 rounded-xl p-3 text-sm">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
          {t("earlierYear")}
        </p>
      ) : null}
      {payment.held_as_credit_while_advances_off ? (
        <p className="bg-info/10 rounded-xl p-3 text-sm">
          {t("heldAsCredit", { amount: formatMoney(payment.held_as_credit_while_advances_off) })}
        </p>
      ) : null}
    </>
  );
}

function paymentColumns(
  t: ReturnType<typeof useTranslations>,
  modes: ReturnType<typeof useTranslations>,
) {
  const columns: DataTableColumn<StaffPaymentRow>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/payments/${row.original.id}`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.retailer.shop_name },
    {
      id: "date",
      header: t("date"),
      cell: ({ row }) => (
        <span className="space-y-0.5">
          <DateText value={row.original.payment_date} />
          {row.original.dated_in_previous_financial_year ? (
            <span className="text-warning-strong block text-xs">{t("earlierYearShort")}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "amount",
      header: t("amount"),
      cell: ({ row }) => <MoneyText value={row.original.amount} />,
    },
    { id: "mode", header: t("mode"), cell: ({ row }) => modes(row.original.mode) },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="flex flex-wrap gap-1">
          <StatusBadge status={row.original.status} labels="paymentStatus" />
          {row.original.needs_review ? (
            <StatusBadge status="NEEDS_REVIEW" labels="paymentStatus" />
          ) : null}
        </span>
      ),
    },
    {
      id: "handover",
      header: t("handover"),
      cell: ({ row }) =>
        row.original.handover_status === "NOT_TRACKED" ? (
          <span className="text-muted-foreground text-xs">{t("recordedInOffice")}</span>
        ) : (
          <span className="space-y-0.5">
            <StatusBadge status={row.original.handover_status} labels="handoverStatus" />
            {row.original.collected_by_name ? (
              <span className="text-muted-foreground block text-xs">
                {row.original.collected_by_name}
              </span>
            ) : null}
          </span>
        ),
    },
    {
      id: "credit",
      header: t("creditLeft"),
      cell: ({ row }) => <MoneyText value={row.original.unapplied_amount} />,
    },
  ];
  return columns;
}

export function PaymentsPage() {
  const t = useTranslations("billing.payments");
  const modes = useTranslations("billing.modes");
  const statuses = useTranslations("paymentStatus");
  const handovers = useTranslations("handoverStatus");
  const { can, feature } = useAuth();
  const online = feature("payments");
  const cursor = useCursor();
  const [search, setSearch] = useListSearch();
  const [mode, setMode] = useState<string>(ALL);
  const [toReview, setToReview] = useState(false);
  const [status, setStatus] = useState<string>(ALL);
  const [handover, setHandover] = useState<string>(ALL);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const term = useDebounced(search.trim(), 300);
  const query = usePaymentsList({
    cursor: cursor.cursor,
    search: term || undefined,
    mode: mode === ALL ? undefined : (mode as PaymentsListMode),
    status: status === ALL ? undefined : (status as PaymentsListStatus),
    handover_status: handover === ALL ? undefined : (handover as PaymentsListHandoverStatus),
    date_from: from || undefined,
    date_to: to || undefined,
    needs_review: toReview || undefined,
  });
  const page = query.data?.data;
  const active = [term, mode !== ALL, status !== ALL, handover !== ALL, from, to, toReview].filter(
    Boolean,
  ).length;
  const canRecord = can("payments.record");
  const canCollect = can("payments.collect");
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canRecord || canCollect ? (
            <Button asChild className="min-h-10 gap-2">
              <Link href="/manage/payments/new">
                {canRecord ? <Plus aria-hidden /> : <HandCoins aria-hidden />}
                {canRecord ? t("record") : t("collect")}
              </Link>
            </Button>
          ) : null
        }
      />
      <PaymentsNav />
      <DataTable
        columns={paymentColumns(t, modes)}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["amount", "credit"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          number: "title",
          shop: "primary",
          amount: "primary",
          status: "primary",
          date: "primary",
          mode: "secondary",
          handover: "secondary",
          credit: "secondary",
        }}
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              setSearch("");
              setMode(ALL);
              setStatus(ALL);
              setHandover(ALL);
              setFrom("");
              setTo("");
              setToReview(false);
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
                  label={t("mode")}
                  value={mode}
                  onChange={(value) => {
                    setMode(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allModes") },
                    ...Object.values(online ? PaymentModeEnum : ManualPaymentModeEnum).map((v) => ({
                      value: v,
                      label: modes(v),
                    })),
                  ]}
                />
                {online ? (
                  <label className="flex min-h-10 items-center gap-2 text-sm max-md:min-h-11">
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={toReview}
                      onChange={(e) => {
                        setToReview(e.target.checked);
                        cursor.reset();
                      }}
                    />
                    {t("needsReviewOnly")}
                  </label>
                ) : null}
                <FilterSelect
                  label={t("status")}
                  value={status}
                  onChange={(value) => {
                    setStatus(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allStatuses") },
                    ...Object.values(PaymentStatusEnum).map((v) => ({
                      value: v,
                      label: statuses(v),
                    })),
                  ]}
                />
                <FilterSelect
                  label={t("handover")}
                  value={handover}
                  onChange={(value) => {
                    setHandover(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allHandovers") },
                    ...Object.values(HandoverStatusEnum).map((v) => ({
                      value: v,
                      label: handovers(v),
                    })),
                  ]}
                />
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
    </>
  );
}

/** What a shop owes and has in credit, and the advances-off notice (ADR-047). */
export function PositionSummary({ dues }: { dues: Dues }) {
  const t = useTranslations("billing.position");
  const p = dues.position;
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm sm:grid-cols-4">
        {[
          ["owed", p.owed],
          ["overdue", p.overdue],
          ["credit", p.unapplied_credit],
          ["net", p.balance],
        ].map(([key, value]) => (
          <div key={key}>
            <dt className="text-muted-foreground text-xs">{t(key!)}</dt>
            <dd className="font-semibold">
              <MoneyText value={value!} />
            </dd>
          </div>
        ))}
      </dl>
      {p.days_overdue > 0 ? (
        <p className="text-destructive text-sm">{t("oldest", { days: p.days_overdue })}</p>
      ) : null}
      {dues.credit_held_while_advances_off ? (
        <p className="bg-info/10 rounded-xl p-3 text-sm">
          {t("heldAsCredit", { amount: formatMoney(dues.credit_held_while_advances_off) })}
        </p>
      ) : null}
    </div>
  );
}

/** Amounts per due, for "pay these first", allocating unused money or moving an allocation.
 * Refunds owed again are paid automatically, never chosen here. */
function DueAmounts({
  dues,
  values,
  onChange,
}: {
  dues: Due[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
}) {
  const t = useTranslations("billing.dues");
  const payable = dues.filter((d) => d.kind !== "REFUND");
  if (!payable.length) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  return (
    <ul className="divide-y rounded-xl border">
      {payable.map((due) => (
        <li key={due.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
          <Label htmlFor={`due-${due.id}`} className="min-w-0 flex-1 font-normal">
            <span className="block font-medium">{due.number}</span>
            <span className="text-muted-foreground text-xs">
              {t("dueOn")} <DateText value={due.due_date} /> · {t("owed")}{" "}
              <MoneyText value={due.balance_due} />
            </span>
          </Label>
          <span className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="min-h-10"
              onClick={() => onChange({ ...values, [due.id]: due.balance_due })}
            >
              {t("all")}
            </Button>
            <Input
              id={`due-${due.id}`}
              inputMode="decimal"
              className="min-h-10 w-28 text-right"
              value={values[due.id] ?? ""}
              onChange={(e) => onChange({ ...values, [due.id]: e.target.value })}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

function chosenDues(dues: Due[], values: Record<string, string>): DueAmountRequest[] {
  return dues
    .filter((d) => d.kind !== "REFUND" && (values[d.id] ?? "").trim() !== "")
    .map((d) => ({
      target_type: d.kind as DueAmountRequest["target_type"],
      target_id: d.id,
      amount: values[d.id]!.trim(),
    }));
}

function PaymentForm({ shop, onChangeShop }: { shop: ShopChoice; onChangeShop: () => void }) {
  const t = useTranslations("billing.payments.form");
  const modes = useTranslations("billing.modes");
  const router = useRouter();
  const client = useQueryClient();
  const { can } = useAuth();
  const { message, fields } = useErrorText();
  const collectOnly = !can("payments.record");
  const duesQuery = useRetailersDues(shop.id);
  const dues = duesQuery.data?.data;
  const [key] = useState(newIdempotencyKey);
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState<string>("CASH");
  const [date, setDate] = useState(todayInIndia);
  const [reference, setReference] = useState("");
  const [cheque, setCheque] = useState("");
  const [chequeDate, setChequeDate] = useState("");
  const [bank, setBank] = useState("");
  const [notes, setNotes] = useState("");
  const [payFirst, setPayFirst] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const earlierYear = Boolean(dues && date && date < dues.financial_year_start);

  async function submit() {
    setBusy(true);
    setError(null);
    setErrors({});
    const body = {
      retailer: shop.id,
      amount: amount.trim(),
      mode: mode as ManualPaymentModeEnum,
      payment_date: date,
      reference_no: reference,
      cheque_number: mode === "CHEQUE" ? cheque : "",
      cheque_date: mode === "CHEQUE" && chequeDate ? chequeDate : null,
      bank_name: mode === "CHEQUE" ? bank : "",
      notes,
    };
    try {
      const response = collectOnly
        ? await paymentsCollect(body, idempotent(key))
        : await paymentsRecord(
            { ...body, pay_first: dues ? chosenDues(dues.dues, payFirst) : [] },
            idempotent(key),
          );
      toast.success(t("saved", { number: response.data.number }));
      refreshMoney(client);
      router.push(`/manage/payments/${response.data.id}`);
    } catch (thrown) {
      setError(message(thrown));
      if (thrown instanceof ApiError) setErrors(fields(thrown));
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {shop.shop_name} <span className="text-muted-foreground text-sm">({shop.code})</span>
        </p>
        <Button type="button" variant="ghost" className="min-h-10" onClick={onChangeShop}>
          {t("otherShop")}
        </Button>
      </div>
      {duesQuery.isLoading ? <CardSkeleton /> : dues ? <PositionSummary dues={dues} /> : null}
      {collectOnly ? <p className="bg-info/10 rounded-xl p-3 text-sm">{t("collectHint")}</p> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label={t("amount")} required error={errors.amount}>
          <Input
            inputMode="decimal"
            className="min-h-10"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </FormField>
        <FormField label={t("mode")} required error={errors.mode}>
          <FormSelect
            value={mode}
            onValueChange={setMode}
            options={Object.values(ManualPaymentModeEnum).map((v) => ({
              value: v,
              label: modes(v),
            }))}
          />
        </FormField>
        <FormField label={t("date")} required hint={t("dateHint")} error={errors.payment_date}>
          <Input
            type="date"
            className="min-h-10"
            value={date}
            max={todayInIndia()}
            onChange={(e) => setDate(e.target.value)}
          />
        </FormField>
        {mode === "CHEQUE" ? (
          <>
            <FormField label={t("chequeNumber")} required error={errors.cheque_number}>
              <Input
                className="min-h-10"
                value={cheque}
                onChange={(e) => setCheque(e.target.value)}
              />
            </FormField>
            <FormField label={t("chequeDate")}>
              <Input
                type="date"
                className="min-h-10"
                value={chequeDate}
                onChange={(e) => setChequeDate(e.target.value)}
              />
            </FormField>
            <FormField label={t("bank")}>
              <Input className="min-h-10" value={bank} onChange={(e) => setBank(e.target.value)} />
            </FormField>
          </>
        ) : (
          <FormField label={t("reference")} hint={t("referenceHint")}>
            <Input
              className="min-h-10"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </FormField>
        )}
      </div>
      {earlierYear ? (
        <p role="status" className="bg-warning/15 flex gap-2 rounded-xl p-3 text-sm">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
          {t("earlierYear")}
        </p>
      ) : null}
      {!collectOnly && dues ? (
        <section className="space-y-2" aria-labelledby="pay-first">
          <h2 id="pay-first" className="font-semibold">
            {t("payFirst")}
          </h2>
          <p className="text-muted-foreground text-xs">{t("payFirstHint")}</p>
          <DueAmounts dues={dues.dues} values={payFirst} onChange={setPayFirst} />
        </section>
      ) : null}
      <FormField label={t("notes")}>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} />
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
        <Button type="submit" className="min-h-10" disabled={busy || !amount.trim()}>
          {collectOnly ? t("saveCollection") : t("save")}
        </Button>
      </FormActions>
    </form>
  );
}

/** Record a payment (office) or a collection (sales staff): the shop, then the money. */
export function NewPaymentPage() {
  const t = useTranslations("billing.payments.form");
  const { can } = useAuth();
  const params = useSearchParams();
  const preset = params.get("retailer") ?? "";
  const presetShop = useRetailersRetrieve(preset, { query: { enabled: Boolean(preset) } }).data
    ?.data;
  const [shop, setShop] = useState<ShopChoice | null>(null);
  const chosen = shop ?? (presetShop ? { ...presetShop } : null);
  const collect = !can("payments.record");
  return (
    <>
      <PageHeader
        title={collect ? t("collectTitle") : t("title")}
        description={collect ? t("collectDescription") : t("description")}
      />
      <PaymentsNav />
      {chosen ? (
        <PaymentForm
          key={chosen.id}
          shop={chosen}
          onChangeShop={() => {
            setShop(null);
            if (preset) window.history.replaceState(null, "", "/manage/payments/new");
          }}
        />
      ) : preset && !presetShop ? (
        <CardSkeleton />
      ) : (
        <ShopPicker onPick={(s) => setShop(s)} />
      )}
    </>
  );
}

function MoveDialog({ payment, row }: { payment: PaymentDetail; row: UsedFor }) {
  const t = useTranslations("billing.payments.detail");
  const client = useQueryClient();
  const dues = useRetailersDues(payment.retailer.id).data?.data;
  const [values, setValues] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  return (
    <ActionDialog
      trigger={
        <Button variant="ghost" size="sm" className="min-h-10">
          {t("move")}
        </Button>
      }
      title={t("moveTitle", { number: row.target_number })}
      description={t("moveBody", { amount: formatMoney(row.amount) })}
      confirmLabel={t("move")}
      disabled={!reason.trim()}
      onSubmit={async () => {
        await paymentAllocationsReverse(row.id, {
          reason,
          to: dues ? chosenDues(dues.dues, values) : [],
        });
        refreshMoney(client);
      }}
    >
      <div className="space-y-3">
        {dues ? <DueAmounts dues={dues.dues} values={values} onChange={setValues} /> : null}
        <FormField label={t("reason")} required>
          <Input className="min-h-10" value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
      </div>
    </ActionDialog>
  );
}

function AllocateDialog({ payment }: { payment: PaymentDetail }) {
  const t = useTranslations("billing.payments.detail");
  const client = useQueryClient();
  const dues = useRetailersDues(payment.retailer.id).data?.data;
  const [values, setValues] = useState<Record<string, string>>({});
  return (
    <ActionDialog
      trigger={
        <Button variant="outline" className="min-h-10">
          {t("allocate")}
        </Button>
      }
      title={t("allocateTitle")}
      description={t("allocateBody", { amount: formatMoney(payment.unapplied_amount) })}
      confirmLabel={t("allocate")}
      onSubmit={async () => {
        await paymentsAllocate(payment.id, {
          to: dues ? chosenDues(dues.dues, values) : [],
        });
        refreshMoney(client);
      }}
    >
      {dues ? <DueAmounts dues={dues.dues} values={values} onChange={setValues} /> : null}
    </ActionDialog>
  );
}

/** An online payment that didn't match its checkout (ADR-049 item 11): staff look, then note it. */
function ReviewDialog({ payment }: { payment: PaymentDetail }) {
  const t = useTranslations("billing.payments.detail");
  const client = useQueryClient();
  const [note, setNote] = useState("");
  return (
    <ActionDialog
      trigger={<Button className="min-h-10">{t("markReviewed")}</Button>}
      title={t("reviewTitle", { number: payment.number })}
      description={payment.review_reason}
      confirmLabel={t("markReviewed")}
      onSubmit={async () => {
        await paymentReview(payment.id, { note: note.trim() });
        refreshMoney(client);
      }}
    >
      <FormField label={t("reviewNote")} hint={t("reviewNoteHint")}>
        <Textarea rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      </FormField>
    </ActionDialog>
  );
}

function PaymentActions({ payment }: { payment: PaymentDetail }) {
  const t = useTranslations("billing.payments.detail");
  const { can } = useAuth();
  const client = useQueryClient();
  const [clearOn, setClearOn] = useState(todayInIndia);
  const apply = () => refreshMoney(client);
  const cheque = payment.mode === "CHEQUE";
  const open = ["RECEIVED", "PENDING_CLEARANCE"].includes(payment.status);
  const actions = [
    <DocumentButton key="receipt" fetchLink={() => paymentsReceipt(payment.id)}>
      {t("receipt")}
    </DocumentButton>,
  ];
  if (can("payments.record") && payment.handover_status === "WITH_SALESMAN") {
    actions.push(
      <ConfirmDialog
        key="handover"
        trigger={<Button className="min-h-10">{t("handedOver")}</Button>}
        title={t("handedOverTitle", { name: payment.collected_by_name })}
        description={t("handedOverBody", { amount: formatMoney(payment.amount) })}
        confirmLabel={t("handedOver")}
        onConfirm={async () => {
          await paymentsHandover({ payments: [payment.id] });
          apply();
        }}
      />,
    );
  }
  if (cheque && open && can("payments.record")) {
    actions.push(
      <ActionDialog
        key="clear"
        trigger={<Button className="min-h-10">{t("clear")}</Button>}
        title={t("clearTitle", { number: payment.cheque_number ?? "" })}
        description={t(payment.status === "PENDING_CLEARANCE" ? "clearBodyCredit" : "clearBody")}
        confirmLabel={t("clear")}
        onSubmit={async () => {
          await paymentsClear(payment.id, { on: clearOn });
          apply();
        }}
      >
        <FormField label={t("clearedOn")}>
          <Input
            type="date"
            className="min-h-10"
            value={clearOn}
            max={todayInIndia()}
            onChange={(e) => setClearOn(e.target.value)}
          />
        </FormField>
      </ActionDialog>,
    );
  }
  if (cheque && open && can("payments.reverse")) {
    actions.push(
      <ReasonDialog
        key="bounce"
        trigger={
          <Button variant="outline" className="min-h-10">
            {t("bounce")}
          </Button>
        }
        title={t("bounceTitle", { number: payment.cheque_number ?? "" })}
        description={t(
          payment.handover_status === "WITH_SALESMAN" ? "bounceBodyWithSalesman" : "bounceBody",
        )}
        reasonLabel={t("bounceReason")}
        confirmLabel={t("bounce")}
        destructive
        onConfirm={async (reason) => {
          await paymentsBounce(payment.id, { reason });
          apply();
        }}
      />,
    );
  }
  if (
    ["RECEIVED", "CLEARED", "PENDING_CLEARANCE"].includes(payment.status) &&
    can("payments.reverse")
  ) {
    actions.push(
      <ReasonDialog
        key="reverse"
        trigger={
          <Button variant="ghost" className="text-destructive min-h-10">
            {t("reverse")}
          </Button>
        }
        title={t("reverseTitle", { number: payment.number })}
        description={t("reverseBody")}
        reasonLabel={t("reverseReason")}
        confirmLabel={t("reverse")}
        destructive
        onConfirm={async (reason) => {
          await paymentsReverse(payment.id, { reason });
          apply();
        }}
      />,
    );
  }
  if (payment.unapplied_amount !== "0.00" && can("payments.record")) {
    actions.push(<AllocateDialog key="allocate" payment={payment} />);
  }
  if (payment.needs_review && can("payments.record")) {
    actions.push(<ReviewDialog key="review" payment={payment} />);
  }
  return <div className="flex flex-wrap gap-2">{actions}</div>;
}

export function PaymentDetailPage({ paymentId }: { paymentId: string }) {
  const t = useTranslations("billing.payments.detail");
  const modes = useTranslations("billing.modes");
  const { can } = useAuth();
  const query = usePaymentsRetrieve(paymentId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const payment = query.data?.data;
  if (!payment) return <EmptyState title={t("notFound")} />;
  const facts: [string, ReactNode][] = [
    [t("date"), <DateText key="d" value={payment.payment_date} />],
    [t("mode"), modes(payment.mode)],
    ...(payment.mode === "CHEQUE"
      ? ([
          [
            t("cheque"),
            `${payment.cheque_number}${payment.bank_name ? ` · ${payment.bank_name}` : ""}`,
          ],
          [
            t("creditTiming"),
            t(payment.credit_timing === "ON_RECEIPT" ? "onReceipt" : "onClearance"),
          ],
        ] as [string, ReactNode][])
      : payment.reference_no
        ? ([[t("reference"), payment.reference_no]] as [string, ReactNode][])
        : []),
    ...(payment.gateway_payment_id
      ? ([[t("gatewayPayment"), payment.gateway_payment_id]] as [string, ReactNode][])
      : []),
    ...(payment.reviewed_at
      ? ([[t("reviewedAt"), <DateText key="rv" value={payment.reviewed_at} withTime />]] as [
          string,
          ReactNode,
        ][])
      : []),
    [t("recordedBy"), payment.recorded_by_name || "—"],
    ...(payment.handover_status !== "NOT_TRACKED"
      ? ([
          [t("collectedBy"), payment.collected_by_name],
          [
            t("handoverStatus"),
            <StatusBadge key="h" status={payment.handover_status} labels="handoverStatus" />,
          ],
        ] as [string, ReactNode][])
      : []),
    ...(payment.handed_over_at
      ? ([
          [
            t("handedOverAt"),
            <span key="at">
              <DateText value={payment.handed_over_at} withTime /> · {payment.handed_over_by_name}
            </span>,
          ],
        ] as [string, ReactNode][])
      : []),
    ...(payment.reversal_reason
      ? ([[t("reversalReason"), payment.reversal_reason]] as [string, ReactNode][])
      : []),
  ];
  return (
    <>
      <Link
        href="/manage/payments"
        className="text-muted-foreground mb-4 inline-flex min-h-10 items-center gap-1 text-sm hover:underline max-md:min-h-11"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("back")}
      </Link>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
              {t("heading", { number: payment.number })}
              <StatusBadge status={payment.status} labels="paymentStatus" />
            </h1>
            <p className="text-muted-foreground text-sm">
              <Link
                href={`/manage/retailers/${payment.retailer.id}/ledger`}
                className="hover:underline"
              >
                {payment.retailer.shop_name}
              </Link>
              {" · "}
              <MoneyText value={payment.amount} className="text-foreground font-semibold" />
            </p>
          </div>
          <PaymentActions payment={payment} />
        </div>
        <PaymentNotices payment={payment} />
        {payment.needs_review ? (
          <p role="status" className="bg-warning/15 flex gap-2 rounded-xl p-3 text-sm">
            <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
            {t("needsReview", { reason: payment.review_reason ?? "" })}
          </p>
        ) : null}
        <div className="grid gap-6 xl:grid-cols-[1fr_24rem] xl:items-start">
          <section className="space-y-2" aria-labelledby="payment-used">
            <h2 id="payment-used" className="font-semibold">
              {t("usedFor")}
            </h2>
            <UsedForList
              rows={payment.used_for}
              action={
                can("payments.record")
                  ? (row) => <MoveDialog payment={payment} row={row} />
                  : undefined
              }
            />
            {payment.unapplied_amount !== "0.00" ? (
              <p className="text-sm">
                {t("creditLeft")} <MoneyText value={payment.unapplied_amount} />
              </p>
            ) : null}
            <DocumentLinksCard kind="RECEIPT" objectId={payment.id} />
          </section>
          <aside className="rounded-xl border p-4">
            <dl className="space-y-2 text-sm">
              {facts.map(([label, value]) => (
                <div key={label} className="flex flex-wrap justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="text-right">{value}</dd>
                </div>
              ))}
            </dl>
            {payment.notes ? <p className="mt-3 text-sm">{payment.notes}</p> : null}
          </aside>
        </div>
      </div>
    </>
  );
}

/** Collections still with salesmen: totals per salesman, and bulk "Handed over". */
export function HandoverPage() {
  const t = useTranslations("billing.handover");
  const paymentsT = useTranslations("billing.payments");
  const modes = useTranslations("billing.modes");
  const client = useQueryClient();
  const { message } = useErrorText();
  const cursor = useCursor();
  const report = useReportsCollectionsPendingHandover();
  const query = usePaymentsList({ handover_status: "WITH_SALESMAN", cursor: cursor.cursor });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const rows = report.data?.data ?? [];
  const page = query.data?.data;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PaymentsNav />
      <section className="mb-6 space-y-2" aria-labelledby="per-salesman">
        <h2 id="per-salesman" className="font-semibold">
          {t("perSalesman")}
        </h2>
        {report.isLoading ? (
          <CardSkeleton />
        ) : report.error ? (
          <ErrorState error={report.error} onRetry={() => void report.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title={t("nothing")} description={t("nothingBody")} />
        ) : (
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((row) => (
              <li key={row.salesman_id} className="rounded-xl border p-4 text-sm">
                <p className="font-medium">{row.salesman_name}</p>
                <p className="text-lg font-semibold">
                  <MoneyText value={row.amount} />
                </p>
                <p className="text-muted-foreground text-xs">
                  {t("count", { count: row.count })} · {t("oldest")} <DateText value={row.oldest} />
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <DataTable
        columns={paymentColumns(paymentsT, modes).filter((c) => c.id !== "credit")}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["amount"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("nothing"), description: t("nothingBody") }}
        cardLayout={{
          number: "title",
          shop: "primary",
          amount: "primary",
          handover: "primary",
          date: "secondary",
          mode: "secondary",
          status: "secondary",
        }}
        selection={{
          selected,
          onChange: setSelected,
          actions: (
            <Button
              className="min-h-10"
              onClick={async () => {
                try {
                  await paymentsHandover({ payments: [...selected] });
                  toast.success(t("done", { count: selected.size }));
                  setSelected(new Set());
                  refreshMoney(client);
                } catch (error) {
                  toast.error(message(error));
                }
              }}
            >
              {t("markHandedOver")}
            </Button>
          ),
          pageLabel: t("selectPage"),
          rowLabel: (row) => t("selectRow", { number: row.number }),
          regionLabel: t("selectionBar"),
        }}
      />
    </>
  );
}
