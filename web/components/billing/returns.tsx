"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { FreeLineLabel } from "@/components/shop/free-goods";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getReturnRequestsListQueryKey,
  getReturnRequestsRetrieveQueryKey,
  returnRequestsApprove,
  returnRequestsReject,
  useReturnRequestsList,
  useReturnRequestsRetrieve,
} from "@/lib/api/generated/endpoints/billing/billing";
import type { ReturnRequest, ReturnRequestsListStatus } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

import { BillingNav } from "./billing-nav";

const ALL = "all";
const DISPOSITIONS = ["RETURN_TO_STOCK", "DAMAGED", "NOT_RETURNED"] as const;
type Disposition = (typeof DISPOSITIONS)[number];

function items(request: ReturnRequest): string {
  return request.lines.map((line) => `${formatQty(line.quantity)} ${line.description}`).join(", ");
}

/** Return requests from shops (ADR-057 item 3): those waiting first by default. */
export function ReturnRequestsPage() {
  const t = useTranslations("billing.returns");
  const tReason = useTranslations("shop.returns.reasons");
  const cursor = useCursor();
  const [status, setStatus] = useState<string>("REQUESTED");
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search.trim());
  const query = useReturnRequestsList({
    cursor: cursor.cursor,
    status: status === ALL ? undefined : (status as ReturnRequestsListStatus),
    search: debounced || undefined,
  });
  const page = query.data?.data;
  const columns: DataTableColumn<ReturnRequest>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/invoices/returns/${row.original.id}`}
          className="font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    { id: "shop", header: t("shop"), cell: ({ row }) => row.original.retailer.shop_name },
    {
      id: "bill",
      header: t("bill"),
      cell: ({ row }) => (
        <Link
          href={`/manage/invoices/${row.original.invoice.id}`}
          className="whitespace-nowrap hover:underline"
        >
          {row.original.invoice.number}
        </Link>
      ),
    },
    { id: "items", header: t("items"), cell: ({ row }) => items(row.original) },
    { id: "reason", header: t("reason"), cell: ({ row }) => tReason(row.original.reason) },
    {
      id: "asked",
      header: t("asked"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} labels="returnRequestStatus" />,
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <BillingNav />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          status === "REQUESTED" && !debounced
            ? { title: t("noneWaitingTitle"), description: t("noneWaitingBody") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={{
          number: "title",
          shop: "primary",
          items: "primary",
          status: "primary",
          bill: "secondary",
          reason: "secondary",
          asked: "secondary",
        }}
        toolbar={
          <FilterBar
            active={status === "REQUESTED" ? 0 : 1}
            onClear={() => {
              setStatus("REQUESTED");
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
              <FilterSelect
                label={t("status")}
                value={status}
                onChange={(v) => {
                  setStatus(v);
                  cursor.reset();
                }}
                options={[
                  { value: "REQUESTED", label: t("waiting") },
                  { value: "APPROVED", label: t("approved") },
                  { value: "REJECTED", label: t("rejected") },
                  { value: "CANCELLED", label: t("cancelled") },
                  { value: ALL, label: t("anyStatus") },
                ]}
              />
            }
          />
        }
      />
    </>
  );
}

interface LineDecision {
  quantity: string;
  disposition: Disposition;
}

function Decide({ request }: { request: ReturnRequest }) {
  const t = useTranslations("billing.returns");
  const tDisposition = useTranslations("billing.returns.dispositions");
  const errors = useErrorText();
  const client = useQueryClient();
  const [decisions, setDecisions] = useState<Record<string, LineDecision>>(() =>
    Object.fromEntries(
      request.lines.map((line) => [
        line.id,
        { quantity: formatQty(line.quantity), disposition: "RETURN_TO_STOCK" as Disposition },
      ]),
    ),
  );
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getReturnRequestsRetrieveQueryKey(request.id) }),
      client.invalidateQueries({ queryKey: getReturnRequestsListQueryKey() }),
      client.invalidateQueries({ queryKey: ["/api/v1/dashboard/"] }),
    ]);
  };
  const set = (id: string, change: Partial<LineDecision>) =>
    setDecisions((all) => ({ ...all, [id]: { ...all[id]!, ...change } }));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("decide")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-3">
          {request.lines.map((line) => (
            <li key={line.id} className="grid gap-2 text-sm sm:grid-cols-[1fr_7rem_14rem]">
              <span className="min-w-0">
                <span className="block font-medium">{line.description}</span>
                {line.is_free ? <FreeLineLabel scheme="" /> : null}
                <span className="text-muted-foreground block text-xs">
                  {t("askedOf", {
                    qty: formatQty(line.quantity),
                    invoiced: formatQty(line.invoiced_quantity),
                    unit: line.unit_code,
                  })}
                </span>
              </span>
              <Input
                aria-label={t("approveQty", { name: line.description })}
                inputMode="decimal"
                value={decisions[line.id]?.quantity ?? ""}
                onChange={(e) => set(line.id, { quantity: e.target.value })}
                className="min-h-10 text-right"
              />
              <FormSelect
                aria-label={t("whatHappened", { name: line.description })}
                value={decisions[line.id]?.disposition ?? "RETURN_TO_STOCK"}
                onValueChange={(v) => set(line.id, { disposition: v as Disposition })}
                options={DISPOSITIONS.map((code) => ({ value: code, label: tDisposition(code) }))}
              />
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2">
          <ConfirmDialog
            trigger={<Button className="min-h-10">{t("approve")}</Button>}
            title={t("approveTitle", { number: request.number })}
            description={t("approveBody")}
            confirmLabel={t("approve")}
            onConfirm={async () => {
              try {
                await returnRequestsApprove(request.id, {
                  lines: request.lines.map((line) => ({
                    line: line.id,
                    quantity: (decisions[line.id]?.quantity ?? "0").trim() || "0",
                    disposition: decisions[line.id]?.disposition ?? "RETURN_TO_STOCK",
                  })),
                });
                toast.success(t("approvedToast"));
              } catch (err) {
                toast.error(errors.message(err));
              }
              await refresh();
            }}
          />
          <ReasonDialog
            destructive
            trigger={
              <Button variant="outline" className="min-h-10">
                {t("reject")}
              </Button>
            }
            title={t("rejectTitle", { number: request.number })}
            description={t("rejectBody")}
            reasonLabel={t("rejectReason")}
            confirmLabel={t("reject")}
            onConfirm={async (reason) => {
              await returnRequestsReject(request.id, { reason });
              toast.success(t("rejectedToast"));
              await refresh();
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function ReturnRequestPage({ requestId }: { requestId: string }) {
  const t = useTranslations("billing.returns");
  const tReason = useTranslations("shop.returns.reasons");
  const tDisposition = useTranslations("billing.returns.dispositions");
  const { can } = useAuth();
  const query = useReturnRequestsRetrieve(requestId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const request = query.data.data;
  return (
    <>
      <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
        <Link href="/manage/invoices/returns">
          <ArrowLeft aria-hidden />
          {t("back")}
        </Link>
      </Button>
      <PageHeader
        title={request.number}
        description={`${request.retailer.shop_name} · ${request.invoice.number}`}
      />
      <div className="max-w-3xl space-y-6">
        <dl className="grid gap-3 rounded-xl border p-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t("status")}</dt>
            <dd>
              <StatusBadge status={request.status} labels="returnRequestStatus" />
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("asked")}</dt>
            <dd>
              <DateText value={request.created_at} withTime />
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("reason")}</dt>
            <dd>
              {tReason(request.reason)}
              {request.note ? `: ${request.note}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("bill")}</dt>
            <dd>
              <Link
                href={`/manage/invoices/${request.invoice.id}`}
                className="text-brand-700 hover:underline"
              >
                {request.invoice.number}
              </Link>
            </dd>
          </div>
          {request.credit_note ? (
            <div>
              <dt className="text-muted-foreground">{t("creditNote")}</dt>
              <dd>
                <Link
                  href={`/manage/invoices/credit-notes/${request.credit_note.id}`}
                  className="text-brand-700 hover:underline"
                >
                  {request.credit_note.number}
                </Link>
              </dd>
            </div>
          ) : null}
          {request.decision_note ? (
            <div className="sm:col-span-2">
              <dt className="text-muted-foreground">{t("rejectReason")}</dt>
              <dd>{request.decision_note}</dd>
            </div>
          ) : null}
        </dl>
        {request.status === "REQUESTED" && can("invoices.manage") ? (
          <Decide request={request} />
        ) : (
          <ul className="divide-y rounded-xl border">
            {request.lines.map((line) => (
              <li key={line.id} className="flex flex-wrap justify-between gap-2 p-3 text-sm">
                <span>{line.description}</span>
                <span className="text-muted-foreground">
                  {t("askedApproved", {
                    asked: formatQty(line.quantity),
                    approved: formatQty(line.approved_quantity ?? "0"),
                  })}
                  {line.disposition ? ` · ${tDisposition(line.disposition)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
