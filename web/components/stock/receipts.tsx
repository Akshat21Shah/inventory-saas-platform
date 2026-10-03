"use client";

import { PackagePlus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FormActions } from "@/components/shared/form-actions";
import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  stockReceiptsCompleteCosts,
  useStockReceiptsList,
  useStockReceiptsRetrieve,
} from "@/lib/api/generated/endpoints/inventory/inventory";
import type { Receipt, ReceiptDetail, ReceiptLine } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { cn } from "@/lib/utils";

import { ProductCell } from "./product-cell";
import { ReceiptEditor } from "./receipt-editor";
import { BackTo } from "./shared";

type Tab = "all" | "DRAFT" | "POSTED" | "awaiting";

export function ReceiptsPage() {
  const t = useTranslations("stock.receipts");
  const { can } = useAuth();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("awaiting_cost") === "true" ? "awaiting" : "all");
  const cursor = useCursor();
  const query = useStockReceiptsList({
    cursor: cursor.cursor,
    status: tab === "DRAFT" || tab === "POSTED" ? tab : undefined,
    awaiting_cost: tab === "awaiting" ? true : undefined,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const tabs: [Tab, string][] = [
    ["all", t("all")],
    ["DRAFT", t("drafts")],
    ["POSTED", t("posted")],
    ...(can("costs.view") ? ([["awaiting", t("awaitingCost")]] as [Tab, string][]) : []),
  ];
  const showCost = rows.some((row) => row.total_cost !== null);

  const columns: DataTableColumn<Receipt>[] = [
    {
      id: "receipt",
      header: t("receipt"),
      cell: ({ row }) => (
        <Link
          href={`/manage/stock/inwards/${row.original.id}`}
          className="text-primary flex min-h-10 flex-col justify-center font-medium hover:underline"
        >
          {row.original.number ?? t("draft")}
          <span className="text-muted-foreground text-xs font-normal">
            <DateText value={row.original.posted_at ?? row.original.created_at} />
          </span>
        </Link>
      ),
    },
    {
      id: "supplier",
      header: t("supplier"),
      cell: ({ row }) => row.original.supplier_name || "—",
    },
    { id: "bill", header: t("bill"), cell: ({ row }) => row.original.bill_number || "—" },
    { id: "lines", header: t("lines"), cell: ({ row }) => row.original.line_count },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="flex flex-wrap gap-1">
          <StatusBadge status={row.original.status} />
          {row.original.cost_pending_lines ? (
            <Badge variant="outline">
              {t("costPending", { count: row.original.cost_pending_lines })}
            </Badge>
          ) : null}
        </span>
      ),
    },
    ...(showCost
      ? [
          {
            id: "total",
            header: t("total"),
            cell: ({ row }: { row: { original: Receipt } }) =>
              row.original.total_cost ? <MoneyText value={row.original.total_cost} /> : "—",
          } satisfies DataTableColumn<Receipt>,
        ]
      : []),
    {
      id: "by",
      header: t("by"),
      cell: ({ row }) => row.original.posted_by || row.original.created_by,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("stock.inward") ? (
            <Button asChild className="min-h-10">
              <Link href="/manage/stock/inwards/new">
                <PackagePlus aria-hidden />
                {t("receive")}
              </Link>
            </Button>
          ) : null
        }
      />
      <div
        role="tablist"
        aria-label={t("filter")}
        className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4"
      >
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => {
              setTab(value);
              cursor.reset();
            }}
            className={cn(
              "min-h-11 shrink-0 rounded-full border px-4 text-sm whitespace-nowrap md:min-h-10",
              tab === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["lines", "total"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          tab === "awaiting"
            ? { title: t("noneAwaiting"), description: t("noneAwaitingBody") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={{
          receipt: "title",
          status: "primary",
          supplier: "primary",
          bill: "secondary",
          lines: "secondary",
          total: "secondary",
          by: "secondary",
        }}
      />
    </>
  );
}

function Received({ line }: { line: ReceiptLine }) {
  const t = useTranslations("stock.receipt");
  const base = line.product.unit.code;
  if (line.entered_unit === "PACK" && line.product.pack_unit) {
    return (
      <span>
        <QtyText value={line.entered_qty} unit={line.product.pack_unit.code} />{" "}
        <span className="text-muted-foreground text-xs">
          {t("equals")} <QtyText value={line.quantity} unit={base} />
        </span>
      </span>
    );
  }
  return <QtyText value={line.quantity} unit={base} />;
}

function CompleteCosts({ receipt, onDone }: { receipt: ReceiptDetail; onDone: () => void }) {
  const t = useTranslations("stock.receipt");
  const errors = useErrorText();
  const key = useRef(newIdempotencyKey());
  const pending = receipt.lines.filter((line) => line.cost_status === "PENDING");
  const [costs, setCosts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const filled = pending.filter((line) => costs[line.id]?.trim());

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await stockReceiptsCompleteCosts(
        receipt.id,
        {
          costs: filled.map((line) => ({ line_id: line.id, entered_cost: costs[line.id]!.trim() })),
        },
        idempotent(key.current),
      );
      key.current = newIdempotencyKey();
      toast.success(t("costsSaved", { count: filled.length }));
      setCosts({});
      onDone();
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("completeTitle")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("completeHelp")}</p>
          <ul className="space-y-3">
            {pending.map((line) => {
              const unit =
                line.entered_unit === "PACK" && line.product.pack_unit
                  ? line.product.pack_unit.code
                  : line.product.unit.code;
              return (
                <li key={line.id}>
                  <label className="grid gap-1 text-sm sm:grid-cols-[1fr_12rem] sm:items-center sm:gap-3">
                    <span>
                      <span className="font-medium">{line.product.name}</span>{" "}
                      <span className="text-muted-foreground">
                        · <Received line={line} />
                      </span>
                      <span className="text-muted-foreground block text-xs">
                        {t("costPer", { unit })}
                      </span>
                    </span>
                    <Input
                      inputMode="decimal"
                      value={costs[line.id] ?? ""}
                      onChange={(e) => setCosts({ ...costs, [line.id]: e.target.value })}
                      className="h-11 text-right"
                    />
                  </label>
                </li>
              );
            })}
          </ul>
          <FormActions>
            <Button type="submit" className="min-h-11" disabled={saving || !filled.length}>
              {t("saveCosts", { count: filled.length })}
            </Button>
          </FormActions>
        </form>
      </CardContent>
    </Card>
  );
}

function ReceiptView({ receipt, onChanged }: { receipt: ReceiptDetail; onChanged: () => void }) {
  const t = useTranslations("stock.receipt");
  const { can } = useAuth();
  const showCost =
    receipt.total_cost !== null || receipt.lines.some((line) => line.entered_cost !== null);
  const columns: DataTableColumn<ReceiptLine>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <ProductCell
          id={row.original.product.id}
          name={row.original.product.name}
          code={row.original.product.code}
        />
      ),
    },
    { id: "received", header: t("received"), cell: ({ row }) => <Received line={row.original} /> },
    ...(showCost
      ? [
          {
            id: "cost",
            header: t("costColumn"),
            cell: ({ row }: { row: { original: ReceiptLine } }) =>
              row.original.entered_cost ? <MoneyText value={row.original.entered_cost} /> : "—",
          } satisfies DataTableColumn<ReceiptLine>,
          {
            id: "line_cost",
            header: t("lineCost"),
            cell: ({ row }: { row: { original: ReceiptLine } }) =>
              row.original.line_cost ? <MoneyText value={row.original.line_cost} /> : "—",
          } satisfies DataTableColumn<ReceiptLine>,
        ]
      : []),
    {
      id: "cost_status",
      header: t("costStatus"),
      cell: ({ row }) =>
        row.original.cost_status === "PENDING" ? (
          <Badge variant="outline">{t("pending")}</Badge>
        ) : row.original.cost_status === "SET" ? (
          t("costEntered")
        ) : (
          "—"
        ),
    },
  ];
  return (
    <>
      <BackTo href="/manage/stock/inwards">{t("back")}</BackTo>
      <PageHeader
        title={receipt.number ?? t("draftTitle")}
        description={
          [receipt.supplier_name, receipt.bill_number].filter(Boolean).join(" · ") || undefined
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <StatusBadge status={receipt.status} />
        {receipt.cost_pending_lines ? (
          <Badge variant="outline">
            {t("linesPending", { count: receipt.cost_pending_lines })}
          </Badge>
        ) : null}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
        {/* min-w-0: a wide lines table scrolls inside its column instead of widening the page */}
        <div className="min-w-0">
          <DataTable
            columns={columns}
            data={[...receipt.lines]}
            getRowId={(row) => row.id}
            numericColumns={["received", "cost", "line_cost"]}
            caption={t("linesCaption")}
            cardLayout={{
              product: "title",
              received: "primary",
              line_cost: "primary",
              cost_status: "primary",
              cost: "secondary",
            }}
          />
        </div>
        <div className="space-y-6">
          <Card>
            <CardContent className="grid grid-cols-2 gap-3 py-5 text-sm">
              <span className="text-muted-foreground">{t("billDate")}</span>
              <span>{receipt.bill_date ? <DateText value={receipt.bill_date} /> : "—"}</span>
              <span className="text-muted-foreground">{t("supplierRef")}</span>
              <span>{receipt.supplier_ref || "—"}</span>
              <span className="text-muted-foreground">{t("postedBy")}</span>
              <span>
                {receipt.posted_by || "—"}
                {receipt.posted_at ? (
                  <span className="text-muted-foreground block text-xs">
                    <DateText value={receipt.posted_at} withTime />
                  </span>
                ) : null}
              </span>
              {receipt.total_cost ? (
                <>
                  <span className="text-muted-foreground">{t("totalCost")}</span>
                  <span className="font-semibold">
                    <MoneyText value={receipt.total_cost} />
                  </span>
                </>
              ) : null}
              {receipt.notes ? (
                <>
                  <span className="text-muted-foreground">{t("notes")}</span>
                  <span className="whitespace-pre-line">{receipt.notes}</span>
                </>
              ) : null}
            </CardContent>
          </Card>
          {receipt.cost_pending_lines && can("costs.manage") ? (
            <CompleteCosts receipt={receipt} onDone={onChanged} />
          ) : null}
        </div>
      </div>
    </>
  );
}

export function ReceiptPage({ receiptId }: { receiptId: string }) {
  const { can } = useAuth();
  const query = useStockReceiptsRetrieve(receiptId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const receipt = query.data.data;
  if (receipt.status === "DRAFT" && can("stock.inward")) {
    return <ReceiptEditor key={receipt.id} draft={receipt} />;
  }
  return <ReceiptView receipt={receipt} onChanged={() => void query.refetch()} />;
}
