"use client";

import { ChevronDown, Minus, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { useSupplierOptions } from "@/components/purchasing/options";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { ApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useIsPhone } from "@/lib/use-media";
import { cn } from "@/lib/utils";

import { ScanBar } from "./scan-bar";
import { BackTo } from "./shared";

export type Product = Pick<
  StockProductRef,
  "id" | "code" | "name" | "unit" | "pack_unit" | "pack_size"
>;

interface Line {
  key: string;
  id?: string;
  product: Product;
  unit: EnteredUnitEnum;
  qty: string;
  cost: string;
  /** From a purchase order: what was ordered and already received (base unit). */
  ordered?: string | null;
  receivedBefore?: string | null;
}

interface OverLine {
  line_id: string;
  product_code: string;
  ordered: string;
  received_before: string;
  receiving: string;
  beyond_tolerance: boolean;
}
interface OverReceipt {
  lines: OverLine[];
  tolerance_percent: number;
  can_confirm: boolean;
}

const TYPED = "typed";

let counter = 0;
const lineKey = () => `line-${++counter}`;

/** One more of the same product (a second scan): +1 in the unit being entered. */
function plusOne(qty: string, delta = 1): string {
  const next = (Number(qty) || 0) + delta;
  return next > 0 ? String(Number(next.toFixed(3))) : "";
}

export function unitLabel(product: Product, unit: EnteredUnitEnum): string {
  return unit === "PACK" && product.pack_unit ? product.pack_unit.code : product.unit.code;
}

/** Base unit or pack, for a line being entered (receipts, purchase orders). */
export function UnitChoice({
  line,
  onChange,
}: {
  line: { product: Product; unit: EnteredUnitEnum };
  onChange: (unit: EnteredUnitEnum) => void;
}) {
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
  const { can, feature } = useAuth();
  // Purchasing (ADR-053): pick a supplier from the list; a draft from an order keeps its own.
  const fromOrder = Boolean(draft?.purchase_order_id);
  const pickSupplier = feature("purchasing") && !fromOrder;
  const supplierOptions = useSupplierOptions(pickSupplier);
  const [supplierId, setSupplierId] = useState(draft?.supplier_id ?? TYPED);
  const [over, setOver] = useState<OverReceipt | null>(null);
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
  const [billOpen, setBillOpen] = useState(Boolean(draft?.supplier_name || draft?.bill_number));
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
        ordered: line.ordered,
        receivedBefore: line.received_before,
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

  function body(): {
    lines: ReceiptLineInputRequest[];
    supplier_id?: string | null;
  } & typeof header {
    return {
      ...header,
      ...(pickSupplier ? { supplier_id: supplierId === TYPED ? null : supplierId } : {}),
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
        if (post) {
          try {
            await stockReceiptsPost(draft.id, {}, idempotent(postKey.current));
          } catch (err) {
            if (err instanceof ApiError && err.code === "OVER_RECEIPT") {
              postKey.current = newIdempotencyKey();
              setOver(err.details as unknown as OverReceipt);
              return;
            }
            throw err;
          }
        }
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

  async function receiveAnyway() {
    if (!draft) return;
    setSaving(true);
    try {
      await stockReceiptsPost(
        draft.id,
        { confirm_over_receipt: true },
        idempotent(postKey.current),
      );
      setOver(null);
      toast.success(t("posted"));
      router.replace(`/manage/stock/inwards/${draft.id}`);
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  const billFields = (
    <>
      {pickSupplier ? (
        <FormField label={t("supplierFromList")} error={fieldErrors.supplier_id}>
          <FormSelect
            value={supplierId}
            onValueChange={setSupplierId}
            options={[{ value: TYPED, label: t("supplierTyped") }, ...supplierOptions]}
          />
        </FormField>
      ) : null}
      {!pickSupplier || supplierId === TYPED ? (
        <FormField label={t("supplier")} error={fieldErrors.supplier_name}>
          <Input
            value={header.supplier_name}
            onChange={(e) => setHeader({ ...header, supplier_name: e.target.value })}
            className="h-11"
            autoComplete="organization"
            readOnly={fromOrder}
          />
        </FormField>
      ) : null}
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
      <PageHeader
        title={draft ? t("draftTitle") : t("newTitle")}
        description={fromOrder ? t("fromOrderBody") : t("newBody")}
      />
      {draft?.purchase_order_id ? (
        <p className="mb-4 text-sm">
          {t("againstOrder")}{" "}
          <Link
            href={`/manage/purchasing/orders/${draft.purchase_order_id}`}
            className="text-primary font-medium hover:underline"
          >
            {draft.purchase_order_number}
          </Link>
        </p>
      ) : null}
      {over ? (
        <OverReceiptDialog
          over={over}
          busy={saving}
          onConfirm={() => void receiveAnyway()}
          onClose={() => setOver(null)}
        />
      ) : null}
      <div className="space-y-6">
        {phone ? (
          // Phones: scanning comes first; the bill details are one tap away.
          <div className="rounded-xl border">
            <button
              type="button"
              aria-expanded={billOpen}
              onClick={() => setBillOpen(!billOpen)}
              className="flex min-h-11 w-full items-center justify-between px-4 text-left font-medium"
            >
              {t("billDetails")}
              <ChevronDown
                aria-hidden
                className={cn("size-4 transition-transform", billOpen && "rotate-180")}
              />
            </button>
            {billOpen ? <div className="grid gap-4 px-4 pb-4">{billFields}</div> : null}
          </div>
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
                          <OrderedHint line={line} />
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
                        <OrderedHint line={line} />
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

/** A line from a purchase order: what was ordered and already received (the server decides,
 * when posting, whether more than ordered needs a confirmation). */
function OrderedHint({ line }: { line: Line }) {
  const t = useTranslations("stock.receipt");
  if (!line.ordered) return null;
  return (
    <p className="text-muted-foreground text-xs">
      {t("orderedHint", {
        ordered: Number(line.ordered),
        received: Number(line.receivedBefore ?? 0),
        unit: line.product.unit.code,
      })}
    </p>
  );
}

function OverReceiptDialog({
  over,
  busy,
  onConfirm,
  onClose,
}: {
  over: OverReceipt;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("stock.receipt.over");
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("body", { percent: over.tolerance_percent })}</DialogDescription>
        </DialogHeader>
        <ul className="space-y-1 text-sm">
          {over.lines.map((line) => (
            <li key={line.line_id} className={line.beyond_tolerance ? "font-medium" : undefined}>
              {t("line", {
                code: line.product_code,
                ordered: Number(line.ordered),
                before: Number(line.received_before),
                receiving: Number(line.receiving),
              })}
            </li>
          ))}
        </ul>
        <p className="text-sm">{over.can_confirm ? t("canConfirm") : t("askManager")}</p>
        <DialogFooter>
          <Button variant="outline" className="min-h-11" onClick={onClose}>
            {t("change")}
          </Button>
          {over.can_confirm ? (
            <Button className="min-h-11" disabled={busy} onClick={onConfirm}>
              {t("confirm")}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
