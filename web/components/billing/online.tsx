"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getPaymentGatewayQueryKey,
  paymentGatewaySave,
  paymentGatewayVerify,
  usePaymentGateway,
  usePaymentIntentsList,
} from "@/lib/api/generated/endpoints/payments/payments";
import {
  PaymentIntentsListStatus,
  type GatewayModeEnum,
  type GatewayProviderEnum,
  type GatewaySettings,
  type PaymentIntentRow,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";

import { PaymentsNav } from "./billing-nav";

const SECRETS = ["key_id", "key_secret", "webhook_secret"] as const;
const ALL = "all";

/** The address the gateway sends its signed webhooks to, with a copy button. */
function WebhookCard({ settings }: { settings: GatewaySettings }) {
  const t = useTranslations("billing.online.settings");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("webhookTitle")}</CardTitle>
        <CardDescription>{t(`webhookBody.${settings.provider}`)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <code className="bg-muted min-w-0 flex-1 rounded-md p-2 text-xs break-all">
            {settings.webhook_url}
          </code>
          <Button
            type="button"
            variant="outline"
            className="min-h-10 gap-2"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(settings.webhook_url);
                toast.success(t("copied"));
              } catch {
                toast.error(t("copyFailed"));
              }
            }}
          >
            <Copy aria-hidden className="size-4" />
            {t("copy")}
          </Button>
        </div>
        {settings.provider === "RAZORPAY" ? (
          <p className="text-muted-foreground text-sm">{t("webhookEvents")}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** The distributor's own gateway account (ADR-049 items 9-10): keys saved encrypted, shown back
 * only by their last characters, checked by the server; live keys only where allowed. */
function GatewayForm({ saved }: { saved: GatewaySettings }) {
  const t = useTranslations("billing.online.settings");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [provider, setProvider] = useState<GatewayProviderEnum>(saved.provider);
  const [mode, setMode] = useState<GatewayModeEnum>(saved.mode);
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setErrors({});
    try {
      await action();
      toast.success(done);
      setValues({});
      await client.invalidateQueries({ queryKey: getPaymentGatewayQueryKey() });
    } catch (err) {
      const byField = fields(err);
      setErrors(byField);
      if (!Object.keys(byField).length) toast.error(message(err));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const typed = Object.fromEntries(
      Object.entries(values)
        .map(([name, value]) => [name, value.trim()])
        .filter(([, value]) => value),
    );
    void run(() => paymentGatewaySave({ provider, mode, ...typed }), t("saved"));
  }

  const modes: GatewayModeEnum[] =
    saved.live_allowed || saved.mode === "LIVE" ? ["TEST", "LIVE"] : ["TEST"];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {t("keysTitle")}
          <StatusBadge status={saved.status} labels="connectionStatus" />
        </CardTitle>
        <CardDescription>{t("keysBody")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("provider")}
              hint={provider === "MOCK" ? t("mockHint") : undefined}
              error={errors.provider}
            >
              <FormSelect
                value={provider}
                onValueChange={(value) => setProvider(value as GatewayProviderEnum)}
                options={saved.providers.map((value) => ({
                  value,
                  label: t(`providers.${value}`),
                }))}
              />
            </FormField>
            <FormField
              label={t("mode")}
              hint={saved.live_allowed ? t("liveHint") : t("testOnly")}
              error={errors.mode}
            >
              <FormSelect
                value={mode}
                onValueChange={(value) => setMode(value as GatewayModeEnum)}
                options={modes.map((value) => ({ value, label: t(`modes.${value}`) }))}
              />
            </FormField>
            {SECRETS.map((name) => (
              <FormField
                key={name}
                label={t(`fields.${name}`)}
                required={!saved.saved[name]}
                hint={
                  saved.saved[name]
                    ? t("savedHint", { value: saved.saved[name] ?? "" })
                    : t(`fieldHints.${name}`)
                }
                error={errors[name]}
              >
                <Input
                  className="h-10"
                  type={name === "key_id" ? "text" : "password"}
                  autoComplete="off"
                  spellCheck={false}
                  value={values[name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                />
              </FormField>
            ))}
          </div>
          {saved.status === "FAILED" && saved.last_error ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              {t("lastError", { error: saved.last_error })}
            </p>
          ) : null}
          {saved.status === "VERIFIED" && saved.verified_at ? (
            <p className="text-muted-foreground text-sm">
              {t("verifiedAt")} <DateText value={saved.verified_at} withTime />
            </p>
          ) : null}
          {saved.status === "CHECKING" ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t("checking")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy} className="min-h-10">
              {t("save")}
            </Button>
            {saved.saved.key_id ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy || saved.status === "CHECKING"}
                className="min-h-10"
                onClick={() => void run(() => paymentGatewayVerify(), t("checkStarted"))}
              >
                {t("check")}
              </Button>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/** Settings → Online payments: only while the super admin has switched payments on. */
export function GatewaySettingsPage() {
  const t = useTranslations("billing.online.settings");
  const { feature } = useAuth();
  const on = feature("payments");
  const query = usePaymentGateway({
    query: {
      enabled: on,
      refetchInterval: (q) => (q.state.data?.data.status === "CHECKING" ? 2000 : false),
    },
  });
  if (!on) return <EmptyState title={t("off")} description={t("offBody")} />;
  const saved = query.data?.data;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error || !saved ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-6">
          <GatewayForm key={`${saved.provider}-${saved.mode}-${saved.status}`} saved={saved} />
          <WebhookCard settings={saved} />
        </div>
      )}
    </>
  );
}

/** Payments → Online checkouts: every "Pay" a shop started, and what the gateway said. */
export function CheckoutsPage() {
  const t = useTranslations("billing.online.checkouts");
  const statuses = useTranslations("checkoutStatus");
  const { feature } = useAuth();
  const on = feature("payments");
  const cursor = useCursor();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>(ALL);
  const term = useDebounced(search.trim(), 300);
  const query = usePaymentIntentsList(
    {
      cursor: cursor.cursor,
      search: term || undefined,
      status: status === ALL ? undefined : (status as PaymentIntentsListStatus),
    },
    { query: { enabled: on } },
  );
  const page = query.data?.data;
  const columns: DataTableColumn<PaymentIntentRow>[] = [
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <Link
          href={`/manage/retailers/${row.original.retailer_id}/ledger`}
          className="text-brand-700 font-medium hover:underline"
        >
          {row.original.shop_name}
        </Link>
      ),
    },
    {
      id: "for",
      header: t("for"),
      cell: ({ row }) =>
        row.original.invoice_id ? (
          <Link href={`/manage/invoices/${row.original.invoice_id}`} className="hover:underline">
            {t("bill", { number: row.original.invoice_number })}
          </Link>
        ) : (
          t(`purposes.${row.original.purpose}`)
        ),
    },
    {
      id: "amount",
      header: t("amount"),
      cell: ({ row }) => <MoneyText value={row.original.amount} />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="space-y-1">
          <StatusBadge status={row.original.status} labels="checkoutStatus" />
          {row.original.last_error ? (
            <span className="text-destructive block max-w-72 text-xs">
              {row.original.last_error}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "started",
      header: t("started"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "receipt",
      header: t("receipt"),
      cell: ({ row }) =>
        row.original.payment_id ? (
          <Link href={`/manage/payments/${row.original.payment_id}`} className="hover:underline">
            {row.original.receipt_number}
          </Link>
        ) : (
          "—"
        ),
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PaymentsNav />
      {!on ? (
        <EmptyState title={t("off")} description={t("offBody")} />
      ) : (
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
            shop: "title",
            amount: "primary",
            status: "primary",
            for: "primary",
            started: "secondary",
            receipt: "secondary",
          }}
          toolbar={
            <FilterBar
              active={[term, status !== ALL].filter(Boolean).length}
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
                  placeholder={t("searchPlaceholder")}
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
                    ...Object.values(PaymentIntentsListStatus).map((value) => ({
                      value,
                      label: statuses(value),
                    })),
                  ]}
                />
              }
            />
          }
        />
      )}
    </>
  );
}
