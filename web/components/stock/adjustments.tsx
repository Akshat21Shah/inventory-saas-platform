"use client";

import { ClipboardCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { DateText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  stockAdjustmentsCreate,
  stockRetrieve,
  useStockAdjustmentsList,
  useStockAdjustmentsRetrieve,
} from "@/lib/api/generated/endpoints/inventory/inventory";
import type {
  Adjustment,
  AdjustmentLine,
  AdjustmentModeEnum,
  ReasonCodeEnum,
  StockRow,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { cn } from "@/lib/utils";

import { ProductCell } from "./product-cell";
import { ScanBar } from "./scan-bar";
import { BackTo } from "./shared";

export const REASONS: ReasonCodeEnum[] = [
  "COUNT_CORRECTION",
  "DAMAGE",
  "EXPIRY",
  "THEFT",
  "OPENING_STOCK",
  "OTHER",
];
const MODES: AdjustmentModeEnum[] = ["COUNTED", "ADD", "REMOVE"];

type Product = Pick<StockRow, "id" | "code" | "name" | "unit" | "on_hand">;
interface Line {
  key: string;
  product: Product;
  mode: AdjustmentModeEnum;
  qty: string;
}
let counter = 0;

/** "+3" / "−2" for a signed quantity change. */
function Signed({ value, unit }: { value: string; unit: string }) {
  const negative = value.startsWith("-");
  return (
    <span
      className={cn(
        "font-medium tabular-nums",
        negative ? "text-destructive" : "text-success-strong",
      )}
    >
      {negative ? "−" : "+"}
      <QtyText value={value.replace("-", "")} unit={unit} />
    </span>
  );
}

export function AdjustmentEditor() {
  const t = useTranslations("stock.adjustment");
  const reasons = useTranslations("stock.reasons");
  const errors = useErrorText();
  const router = useRouter();
  const params = useSearchParams();
  const key = useRef(newIdempotencyKey());
  const [reason, setReason] = useState<ReasonCodeEnum | "">("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const preset = params.get("product");
  useEffect(() => {
    if (!preset) return;
    stockRetrieve(preset)
      .then((response) => add(response.data))
      .catch(() => undefined);
  }, [preset]);

  function add(product: Product) {
    setLines((current) =>
      current.some((line) => line.product.id === product.id)
        ? current
        : [...current, { key: `adj-${++counter}`, product, mode: "COUNTED", qty: "" }],
    );
  }
  const update = (key: string, change: Partial<Line>) =>
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...change } : l)));

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFieldErrors({});
    try {
      const response = await stockAdjustmentsCreate(
        {
          reason_code: reason as ReasonCodeEnum,
          note,
          lines: lines.map((line) => ({
            product_id: line.product.id,
            mode: line.mode,
            quantity: line.qty.trim() || "0",
          })),
        },
        idempotent(key.current),
      );
      const created = response.data;
      toast.success(
        created.unchanged.length
          ? t("savedWithUnchanged", { number: created.number, count: created.unchanged.length })
          : t("saved", { number: created.number }),
      );
      router.replace(`/manage/stock/adjustments/${created.id}`);
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      toast.error(errors.message(err));
      key.current = newIdempotencyKey();
    } finally {
      setSaving(false);
    }
  }

  const lineError = (index: number) => fieldErrors[`lines.${index + 1}`];
  return (
    <>
      <BackTo href="/manage/stock/adjustments">{t("back")}</BackTo>
      <PageHeader title={t("newTitle")} description={t("newBody")} />
      <form onSubmit={save} className="space-y-6">
        <fieldset>
          <legend className="mb-2 font-medium">{t("reason")}</legend>
          <div className="flex flex-wrap gap-2">
            {REASONS.map((value) => (
              <label
                key={value}
                className={cn(
                  "flex min-h-11 cursor-pointer items-center rounded-full border px-4 text-sm md:min-h-10",
                  reason === value ? "border-brand-400 bg-brand-50 font-medium" : "hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="reason"
                  value={value}
                  checked={reason === value}
                  onChange={() => setReason(value)}
                  className="sr-only"
                />
                {reasons(value)}
              </label>
            ))}
          </div>
          {fieldErrors.reason_code ? (
            <p role="alert" className="text-destructive mt-1 text-sm">
              {fieldErrors.reason_code}
            </p>
          ) : null}
        </fieldset>
        <FormField label={t("note")} error={fieldErrors.note} hint={t("noteHint")}>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} required />
        </FormField>

        <section aria-labelledby="adjust-lines" className="space-y-3">
          <h2 id="adjust-lines" className="text-lg font-semibold">
            {t("linesTitle", { count: lines.length })}
          </h2>
          <ScanBar onPick={add} autoFocus />
          {fieldErrors.lines ? (
            <p role="alert" className="text-destructive text-sm">
              {fieldErrors.lines}
            </p>
          ) : null}
          {lines.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-8 text-center text-sm">
              {t("emptyLines")}
            </p>
          ) : (
            <ul className="space-y-3">
              {lines.map((line, index) => (
                <li key={line.key}>
                  <Card className={cn(lineError(index) && "border-destructive")}>
                    <CardContent className="grid gap-3 py-4 md:grid-cols-[1fr_auto_10rem_auto] md:items-center">
                      <div className="min-w-0">
                        <p className="font-medium">{line.product.name}</p>
                        <p className="text-muted-foreground text-xs">
                          {line.product.code} ·{" "}
                          {t("inStockNow", {
                            qty: Number(line.product.on_hand),
                            unit: line.product.unit.code,
                          })}
                        </p>
                      </div>
                      <div
                        role="radiogroup"
                        aria-label={t("how", { name: line.product.name })}
                        className="flex gap-1"
                      >
                        {MODES.map((mode) => (
                          <button
                            key={mode}
                            type="button"
                            role="radio"
                            aria-checked={line.mode === mode}
                            onClick={() => update(line.key, { mode })}
                            className={cn(
                              "min-h-11 flex-1 rounded-lg border px-3 text-sm whitespace-nowrap md:min-h-9",
                              line.mode === mode
                                ? "border-brand-400 bg-brand-50 font-medium"
                                : "hover:bg-muted",
                            )}
                          >
                            {t(`modes.${mode}`)}
                          </button>
                        ))}
                      </div>
                      <Input
                        inputMode="decimal"
                        value={line.qty}
                        onChange={(e) => update(line.key, { qty: e.target.value })}
                        aria-label={t(`qtyLabel.${line.mode}`, {
                          name: line.product.name,
                          unit: line.product.unit.code,
                        })}
                        placeholder={t(`qtyPlaceholder.${line.mode}`)}
                        className="h-12 text-center text-lg font-semibold md:h-10 md:text-base"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-11 justify-self-end"
                        aria-label={t("remove", { name: line.product.name })}
                        onClick={() => setLines(lines.filter((l) => l.key !== line.key))}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                      {lineError(index) ? (
                        <p role="alert" className="text-destructive text-sm md:col-span-4">
                          {lineError(index)}
                        </p>
                      ) : null}
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
        <FormActions>
          <Button type="submit" className="min-h-11" disabled={saving || !lines.length || !reason}>
            {t("save", { count: lines.length })}
          </Button>
        </FormActions>
      </form>
    </>
  );
}

export function AdjustmentsPage() {
  const t = useTranslations("stock.adjustments");
  const reasons = useTranslations("stock.reasons");
  const { can } = useAuth();
  const cursor = useCursor();
  const query = useStockAdjustmentsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<Adjustment>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/stock/adjustments/${row.original.id}`}
          className="text-primary flex min-h-10 items-center font-medium hover:underline"
        >
          {row.original.number}
        </Link>
      ),
    },
    { id: "reason", header: t("reason"), cell: ({ row }) => reasons(row.original.reason_code) },
    { id: "note", header: t("note"), cell: ({ row }) => row.original.note },
    { id: "lines", header: t("lines"), cell: ({ row }) => row.original.line_count },
    {
      id: "when",
      header: t("when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    { id: "by", header: t("by"), cell: ({ row }) => row.original.created_by },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("stock.adjust") ? (
            <Button asChild className="min-h-10">
              <Link href="/manage/stock/adjustments/new">
                <ClipboardCheck aria-hidden />
                {t("new")}
              </Link>
            </Button>
          ) : null
        }
      />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["lines"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
        cardLayout={{
          number: "title",
          reason: "primary",
          note: "primary",
          lines: "secondary",
          when: "secondary",
          by: "secondary",
        }}
      />
    </>
  );
}

export function AdjustmentPage({ adjustmentId }: { adjustmentId: string }) {
  const t = useTranslations("stock.adjustment");
  const reasons = useTranslations("stock.reasons");
  const query = useStockAdjustmentsRetrieve(adjustmentId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const adjustment = query.data.data;
  const columns: DataTableColumn<AdjustmentLine>[] = [
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
    { id: "mode", header: t("modeColumn"), cell: ({ row }) => t(`modes.${row.original.mode}`) },
    {
      id: "before",
      header: t("before"),
      cell: ({ row }) => <QtyText value={row.original.on_hand_before} />,
    },
    {
      id: "change",
      header: t("change"),
      cell: ({ row }) => (
        <Signed value={row.original.quantity_change} unit={row.original.product.unit.code} />
      ),
    },
  ];
  return (
    <>
      <BackTo href="/manage/stock/adjustments">{t("back")}</BackTo>
      <PageHeader
        title={adjustment.number}
        description={`${reasons(adjustment.reason_code)} · ${adjustment.created_by}`}
      />
      <Card className="mb-6">
        <CardContent className="py-4 text-sm">
          <p className="whitespace-pre-line">{adjustment.note}</p>
          <p className="text-muted-foreground mt-2">
            <DateText value={adjustment.created_at} withTime />
          </p>
        </CardContent>
      </Card>
      <DataTable
        columns={columns}
        data={[...adjustment.lines]}
        getRowId={(row) => row.id}
        numericColumns={["before", "change"]}
        caption={adjustment.number}
        cardLayout={{ product: "title", change: "primary", mode: "primary", before: "secondary" }}
      />
    </>
  );
}
