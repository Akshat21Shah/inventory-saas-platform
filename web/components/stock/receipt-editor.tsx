"use client";

import { Minus, Plus, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  stockReceiptsCreate,
  stockReceiptsDestroy,
  stockReceiptsPost,
  stockReceiptsUpdate,
  stockRetrieve,
} from "@/lib/api/generated/endpoints/inventory/inventory";
import type {
  EnteredUnitEnum,
  ReceiptDetail,
  ReceiptLineInputRequest,
  StockProductRef,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useIsPhone } from "@/lib/use-media";
import { cn } from "@/lib/utils";

import { ScanBar } from "./scan-bar";
import { BackTo } from "./shared";

type Product = Pick<StockProductRef, "id" | "code" | "name" | "unit" | "pack_unit" | "pack_size">;

interface Line {
  key: string;
  id?: string;
  product: Product;
  unit: EnteredUnitEnum;
  qty: string;
  cost: string;
}

let counter = 0;
const lineKey = () => `line-${++counter}`;

/** One more of the same product (a second scan): +1 in the unit being entered. */
function plusOne(qty: string, delta = 1): string {
  const next = (Number(qty) || 0) + delta;
  return next > 0 ? String(Number(next.toFixed(3))) : "";
}

function unitLabel(product: Product, unit: EnteredUnitEnum): string {
  return unit === "PACK" && product.pack_unit ? product.pack_unit.code : product.unit.code;
}

function UnitChoice({ line, onChange }: { line: Line; onChange: (unit: EnteredUnitEnum) => void }) {
  const t = useTranslations("stock.receipt");
  const { product } = line;
  if (!product.pack_unit) return <span className="text-sm">{product.unit.code}</span>;
  const options: [EnteredUnitEnum, string][] = [
    ["BASE", product.unit.code],
    [
      "PACK",
      t("packOf", {
        pack: product.pack_unit.code,
        size: Number(product.pack_size ?? 0),
        unit: product.unit.code,
      }),
    ],
  ];
  return (
    <div role="radiogroup" aria-label={t("unit")} className="flex gap-1">
      {options.map(([value, label]) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={line.unit === value}
          onClick={() => onChange(value)}
          className={cn(
            "min-h-11 rounded-lg border px-3 text-sm whitespace-nowrap md:min-h-9",
            line.unit === value ? "border-brand-400 bg-brand-50 font-medium" : "hover:bg-muted",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function ReceiptEditor({ draft }: { draft?: ReceiptDetail }) {
  const t = useTranslations("stock.receipt");
  const { can } = useAuth();
  const errors = useErrorText();
  const router = useRouter();
  const params = useSearchParams();
  const phone = useIsPhone();
  const canCost = can("costs.view");
  const scanRef = useRef<HTMLInputElement>(null);
  const qtyRefs = useRef(new Map<string, HTMLInputElement>());
  const costRefs = useRef(new Map<string, HTMLInputElement>());
  const createKey = useRef(newIdempotencyKey());
  const postKey = useRef(newIdempotencyKey());
  // The line whose quantity field gets the focus after it is added (laptops).
  const focusNext = useRef<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [header, setHeader] = useState({
    supplier_name: draft?.supplier_name ?? "",
    bill_number: draft?.bill_number ?? "",
    bill_date: draft?.bill_date ?? "",
    supplier_ref: draft?.supplier_ref ?? "",
    notes: draft?.notes ?? "",
  });
  const [lines, setLines] = useState<Line[]>(
    () =>
      draft?.lines.map((line) => ({
        key: lineKey(),
        id: line.id,
        product: line.product,
        unit: line.entered_unit,
        qty: String(Number(line.entered_qty)),
        cost: line.entered_cost ? String(Number(line.entered_cost)) : "",
      })) ?? [],
  );

  // "Receive goods" from a product's stock page starts with that product.
  const preset = params.get("product");
  useEffect(() => {
    if (!preset || draft) return;
    stockRetrieve(preset)
      .then((response) => add(response.data))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for the linked product
  }, [preset]);

  const linesRef = useRef(lines);
  useEffect(() => {
    linesRef.current = lines;
    if (focusNext.current) {
      qtyRefs.current.get(focusNext.current)?.select();
      focusNext.current = null;
    }
  }, [lines]);

  function add(product: Product) {
    const existing = linesRef.current.find((line) => line.product.id === product.id);
    if (existing) {
      toast.message(t("addedAgain", { name: product.name }));
      setLines((current) =>
        current.map((line) =>
          line.key === existing.key ? { ...line, qty: plusOne(line.qty) } : line,
        ),
      );
      return;
    }
    const line: Line = { key: lineKey(), product, unit: "BASE", qty: "1", cost: "" };
    linesRef.current = [...linesRef.current, line];
    setLines((current) => [...current, line]);
    if (!phone) focusNext.current = line.key;
  }

  function update(key: string, change: Partial<Line>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...change } : line)),
    );
  }

  function remove(key: string) {
    setLines((current) => current.filter((line) => line.key !== key));
  }

  /** Laptop keyboard flow: quantity → cost → back to the scan bar for the next product. */
  function onQtyKey(event: KeyboardEvent<HTMLInputElement>, key: string) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const cost = costRefs.current.get(key);
    if (cost) cost.focus();
    else scanRef.current?.focus();
  }
  function onCostKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    scanRef.current?.focus();
  }

  function body(): { lines: ReceiptLineInputRequest[] } & typeof header {
    return {
      ...header,
      lines: lines.map((line) => ({
        ...(line.id ? { id: line.id } : {}),
        product_id: line.product.id,
        entered_unit: line.unit,
        entered_qty: line.qty.trim() || "0",
        ...(canCost ? { entered_cost: line.cost.trim() || null } : {}),
      })),
    };
  }

  function payload() {
    const data = body();
    return { ...data, bill_date: data.bill_date || null };
  }

  function showErrors(err: unknown) {
    const fields = errors.fields(err);
    setFieldErrors(fields);
    toast.error(Object.keys(fields).length ? t("fixLines") : errors.message(err));
  }

  async function save(post: boolean) {
    if (!lines.length) {
      toast.error(t("noLines"));
      return;
    }
    setSaving(true);
    setFieldErrors({});
    try {
      let id = draft?.id;
      if (draft) {
        await stockReceiptsUpdate(draft.id, payload());
        if (post) await stockReceiptsPost(draft.id, idempotent(postKey.current));
      } else {
        const created = await stockReceiptsCreate(
          { ...payload(), post },
          idempotent(createKey.current),
        );
        id = created.data.id;
      }
      toast.success(post ? t("posted") : t("saved"));
      router.replace(`/manage/stock/inwards/${id}`);
    } catch (err) {
      // The dialog closes so the messages next to the lines are visible.
      showErrors(err);
    } finally {
      setSaving(false);
    }
  }

  const billFields = (
    <>
      <FormField label={t("supplier")} error={fieldErrors.supplier_name}>
        <Input
          value={header.supplier_name}
          onChange={(e) => setHeader({ ...header, supplier_name: e.target.value })}
          className="h-11"
          autoComplete="organization"
        />
      </FormField>
      <FormField label={t("billNumber")} error={fieldErrors.bill_number}>
        <Input
          value={header.bill_number}
          onChange={(e) => setHeader({ ...header, bill_number: e.target.value })}
          className="h-11"
        />
      </FormField>
      <FormField label={t("billDate")} error={fieldErrors.bill_date}>
        <Input
          type="date"
          value={header.bill_date}
          onChange={(e) => setHeader({ ...header, bill_date: e.target.value })}
          className="h-11"
        />
      </FormField>
      <FormField label={t("supplierRef")} error={fieldErrors.supplier_ref}>
        <Input
          value={header.supplier_ref}
          onChange={(e) => setHeader({ ...header, supplier_ref: e.target.value })}
          className="h-11"
        />
      </FormField>
    </>
  );
  const lineError = (index: number) => fieldErrors[`lines.${index + 1}`];
  const costLabel = (line: Line) => t("costPer", { unit: unitLabel(line.product, line.unit) });

  return (
    <>
      <BackTo href="/manage/stock/inwards">{t("back")}</BackTo>
      <PageHeader title={draft ? t("draftTitle") : t("newTitle")} description={t("newBody")} />
      <div className="space-y-6">
        {phone ? (
          // Phones: scanning comes first; the bill details are one tap away.
          <details className="rounded-xl border" open={Boolean(draft?.supplier_name)}>
            <summary className="flex min-h-11 cursor-pointer items-center px-4 font-medium">
              {t("billDetails")}
            </summary>
            <div className="grid gap-4 px-4 pb-4">{billFields}</div>
          </details>
        ) : (
          <Card>
            <CardContent className="grid gap-4 py-5 sm:grid-cols-2 lg:grid-cols-4">
              {billFields}
            </CardContent>
          </Card>
        )}

        <section aria-labelledby="lines-title" className="space-y-3">
          <h2 id="lines-title" className="text-lg font-semibold">
            {t("linesTitle", { count: lines.length })}
          </h2>
          <ScanBar onPick={add} autoFocus={!draft} inputRef={scanRef} />
          {fieldErrors.lines ? (
            <p role="alert" className="text-destructive text-sm">
              {fieldErrors.lines}
            </p>
          ) : null}
          {!canCost ? <p className="text-muted-foreground text-sm">{t("noCostNote")}</p> : null}
          {lines.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-8 text-center text-sm">
              {t("emptyLines")}
            </p>
          ) : phone ? (
            <ul className="space-y-3">
              {lines.map((line, index) => (
                <li key={line.key}>
                  <Card className={cn(lineError(index) && "border-destructive")}>
                    <CardContent className="space-y-3 py-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-medium">{line.product.name}</p>
                          <p className="text-muted-foreground text-xs">{line.product.code}</p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-11 shrink-0"
                          aria-label={t("remove", { name: line.product.name })}
                          onClick={() => remove(line.key)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </div>
                      <UnitChoice line={line} onChange={(unit) => update(line.key, { unit })} />
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="size-12"
                          aria-label={t("less", { name: line.product.name })}
                          onClick={() => update(line.key, { qty: plusOne(line.qty, -1) })}
                        >
                          <Minus aria-hidden />
                        </Button>
                        <Input
                          inputMode="decimal"
                          value={line.qty}
                          onChange={(e) => update(line.key, { qty: e.target.value })}
                          aria-label={t("qtyFor", {
                            name: line.product.name,
                            unit: unitLabel(line.product, line.unit),
                          })}
                          className="h-12 flex-1 text-center text-lg font-semibold"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="size-12"
                          aria-label={t("more", { name: line.product.name })}
                          onClick={() => update(line.key, { qty: plusOne(line.qty) })}
                        >
                          <Plus aria-hidden />
                        </Button>
                      </div>
                      {canCost ? (
                        <label className="block text-sm">
                          <span className="mb-1 block font-medium">{costLabel(line)}</span>
                          <Input
                            inputMode="decimal"
                            value={line.cost}
                            onChange={(e) => update(line.key, { cost: e.target.value })}
                            placeholder={t("costOptional")}
                            className="h-12"
                          />
                        </label>
                      ) : null}
                      {lineError(index) ? (
                        <p role="alert" className="text-destructive text-sm">
                          {lineError(index)}
                        </p>
                      ) : null}
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <table className="w-full text-sm">
                <caption className="sr-only">{t("linesCaption")}</caption>
                <thead className="bg-muted/50 text-muted-foreground text-left">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("product")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("unit")}
                    </th>
                    <th scope="col" className="w-32 px-3 py-2 text-right font-medium">
                      {t("quantity")}
                    </th>
                    {canCost ? (
                      <th scope="col" className="w-44 px-3 py-2 text-right font-medium">
                        {t("costColumn")}
                      </th>
                    ) : null}
                    <th scope="col" className="w-12 px-3 py-2">
                      <span className="sr-only">{t("actions")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => (
                    <tr key={line.key} className="border-t align-top">
                      <td className="px-3 py-2">
                        <p className="font-medium">{line.product.name}</p>
                        <p className="text-muted-foreground text-xs">{line.product.code}</p>
                        {lineError(index) ? (
                          <p role="alert" className="text-destructive mt-1 text-xs">
                            {lineError(index)}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <UnitChoice line={line} onChange={(unit) => update(line.key, { unit })} />
                      </td>
                      <td className="px-3 py-2">
                        <Input
                          ref={(el) => {
                            if (el) qtyRefs.current.set(line.key, el);
                            else qtyRefs.current.delete(line.key);
                          }}
                          inputMode="decimal"
                          value={line.qty}
                          onChange={(e) => update(line.key, { qty: e.target.value })}
                          onKeyDown={(e) => onQtyKey(e, line.key)}
                          aria-label={t("qtyFor", {
                            name: line.product.name,
                            unit: unitLabel(line.product, line.unit),
                          })}
                          className="h-9 text-right tabular-nums"
                        />
                      </td>
                      {canCost ? (
                        <td className="px-3 py-2">
                          <Input
                            ref={(el) => {
                              if (el) costRefs.current.set(line.key, el);
                              else costRefs.current.delete(line.key);
                            }}
                            inputMode="decimal"
                            value={line.cost}
                            onChange={(e) => update(line.key, { cost: e.target.value })}
                            onKeyDown={onCostKey}
                            aria-label={`${costLabel(line)}: ${line.product.name}`}
                            placeholder={t("costOptional")}
                            className="h-9 text-right tabular-nums"
                          />
                        </td>
                      ) : null}
                      <td className="px-3 py-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t("remove", { name: line.product.name })}
                          onClick={() => remove(line.key)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <FormField label={t("notes")}>
          <Textarea
            value={header.notes}
            onChange={(e) => setHeader({ ...header, notes: e.target.value })}
            rows={2}
          />
        </FormField>

        <FormActions>
          {draft ? (
            <ConfirmDialog
              destructive
              trigger={
                <Button type="button" variant="ghost" className="min-h-11" disabled={saving}>
                  {t("deleteDraft")}
                </Button>
              }
              title={t("deleteTitle")}
              description={t("deleteBody")}
              confirmLabel={t("deleteDraft")}
              onConfirm={async () => {
                await stockReceiptsDestroy(draft.id);
                toast.success(t("deleted"));
                router.replace("/manage/stock/inwards");
              }}
            />
          ) : null}
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            disabled={saving}
            onClick={() => void save(false)}
          >
            {draft ? t("saveDraft") : t("saveAsDraft")}
          </Button>
          <ConfirmDialog
            trigger={
              <Button type="button" className="min-h-11" disabled={saving || !lines.length}>
                {draft ? t("post") : t("saveAndPost")}
              </Button>
            }
            title={t("postTitle", { count: lines.length })}
            description={t("postBody")}
            confirmLabel={t("post")}
            onConfirm={() => save(true)}
          />
        </FormActions>
      </div>
    </>
  );
}
