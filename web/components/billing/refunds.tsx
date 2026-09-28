"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  refundsRecord,
  refundsVoucher,
  useRefundsList,
  useRefundsRetrieve,
} from "@/lib/api/generated/endpoints/payments/payments";
import { useRetailersDues } from "@/lib/api/generated/endpoints/receivables/receivables";
import { useRetailersRetrieve } from "@/lib/api/generated/endpoints/retailers/retailers";
import { RefundModeEnum, type Refund } from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";

import { PaymentsNav } from "./billing-nav";
import { DocumentButton } from "./document-button";
import { AppliedList } from "./invoices";
import { PositionSummary, type ShopChoice } from "./payments";
import { ShopPicker, todayInIndia } from "./shop-picker";

export function RefundsPage() {
  const t = useTranslations("billing.refunds");
  const modes = useTranslations("billing.modes");
  const { can } = useAuth();
  const cursor = useCursor();
  const query = useRefundsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<Refund>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/payments/refunds/${row.original.id}`}
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
      cell: ({ row }) => <DateText value={row.original.refund_date} />,
    },
    { id: "mode", header: t("mode"), cell: ({ row }) => modes(row.original.mode) },
    {
      id: "amount",
      header: t("amount"),
      cell: ({ row }) => <MoneyText value={row.original.amount} />,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("payments.record") ? (
            <Button asChild className="min-h-10 gap-2">
              <Link href="/manage/payments/refunds/new">
                <Plus aria-hidden />
                {t("new")}
              </Link>
            </Button>
          ) : null
        }
      />
      <PaymentsNav />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["amount"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          number: "title",
          shop: "primary",
          amount: "primary",
          date: "primary",
          mode: "secondary",
        }}
      />
    </>
  );
}

function RefundForm({ shop, onChangeShop }: { shop: ShopChoice; onChangeShop: () => void }) {
  const t = useTranslations("billing.refunds.form");
  const modes = useTranslations("billing.modes");
  const router = useRouter();
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const dues = useRetailersDues(shop.id);
  const [key] = useState(newIdempotencyKey);
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState<string>("BANK_TRANSFER");
  const [date, setDate] = useState(todayInIndia);
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const credit = dues.data?.data.position.unapplied_credit ?? "0.00";
  return (
    <form
      className="max-w-2xl space-y-6"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        setErrors({});
        try {
          const response = await refundsRecord(
            {
              retailer: shop.id,
              amount: amount.trim(),
              mode: mode as RefundModeEnum,
              refund_date: date,
              reference_no: reference,
              notes,
            },
            idempotent(key),
          );
          toast.success(t("saved", { number: response.data.number }));
          void client.invalidateQueries();
          router.push(`/manage/payments/refunds/${response.data.id}`);
        } catch (thrown) {
          setError(message(thrown));
          if (thrown instanceof ApiError) setErrors(fields(thrown));
        } finally {
          setBusy(false);
        }
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
      {dues.isLoading ? (
        <CardSkeleton />
      ) : dues.data ? (
        <PositionSummary dues={dues.data.data} />
      ) : null}
      {dues.data && credit === "0.00" ? (
        <p className="bg-muted rounded-xl p-3 text-sm">{t("noCredit")}</p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField
          label={t("amount")}
          required
          hint={t("upTo", { amount: credit })}
          error={errors.amount}
        >
          <Input
            inputMode="decimal"
            className="min-h-10"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </FormField>
        <FormField label={t("mode")} required>
          <FormSelect
            value={mode}
            onValueChange={setMode}
            options={Object.values(RefundModeEnum).map((v) => ({ value: v, label: modes(v) }))}
          />
        </FormField>
        <FormField label={t("date")} required error={errors.refund_date}>
          <Input
            type="date"
            className="min-h-10"
            value={date}
            max={todayInIndia()}
            onChange={(e) => setDate(e.target.value)}
          />
        </FormField>
        <FormField label={t("reference")}>
          <Input
            className="min-h-10"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
        </FormField>
      </div>
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
          {t("save")}
        </Button>
      </FormActions>
    </form>
  );
}

/** Pay a shop back from its credit balance (never more than it has; ADR-047). */
export function NewRefundPage() {
  const t = useTranslations("billing.refunds.form");
  const params = useSearchParams();
  const preset = params.get("retailer") ?? "";
  const presetShop = useRetailersRetrieve(preset, { query: { enabled: Boolean(preset) } }).data
    ?.data;
  const [shop, setShop] = useState<ShopChoice | null>(null);
  const chosen = shop ?? (presetShop ? { ...presetShop } : null);
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PaymentsNav />
      {chosen ? (
        <RefundForm
          key={chosen.id}
          shop={chosen}
          onChangeShop={() => {
            setShop(null);
            if (preset) window.history.replaceState(null, "", "/manage/payments/refunds/new");
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

export function RefundDetailPage({ refundId }: { refundId: string }) {
  const t = useTranslations("billing.refunds");
  const modes = useTranslations("billing.modes");
  const query = useRefundsRetrieve(refundId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const refund = query.data?.data;
  if (!refund) return <EmptyState title={t("notFound")} />;
  return (
    <>
      <Link
        href="/manage/payments/refunds"
        className="text-muted-foreground mb-4 inline-flex min-h-10 items-center gap-1 text-sm hover:underline max-md:min-h-11"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("back")}
      </Link>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold">{t("heading", { number: refund.number })}</h1>
            <p className="text-muted-foreground text-sm">
              <Link
                href={`/manage/retailers/${refund.retailer.id}/ledger`}
                className="hover:underline"
              >
                {refund.retailer.shop_name}
              </Link>
              {" · "}
              <DateText value={refund.refund_date} />
              {" · "}
              {modes(refund.mode)}
              {refund.reference_no ? ` · ${refund.reference_no}` : ""}
            </p>
            <p className="text-xl font-semibold">
              <MoneyText value={refund.amount} />
            </p>
          </div>
          <DocumentButton fetchLink={() => refundsVoucher(refund.id)}>
            {t("voucher")}
          </DocumentButton>
        </div>
        <section className="max-w-2xl space-y-2" aria-labelledby="refund-from">
          <h2 id="refund-from" className="font-semibold">
            {t("paidFrom")}
          </h2>
          <AppliedList rows={refund.paid_from} />
          {refund.notes ? <p className="text-sm">{refund.notes}</p> : null}
          <p className="text-muted-foreground text-xs">
            {t("recordedBy", { name: refund.recorded_by_name || "—" })}
          </p>
        </section>
      </div>
    </>
  );
}
