"use client";

import { Percent } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { MoneyText } from "@/components/shared/money-text";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  priceListsAdjust,
  priceListsAdjustPreview,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import type { AdjustPreview, Warning } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

type Scope = "category" | "brand";

/** "+5% on all Brand X" for a price list, previewed by the server before anything changes. */
export function BulkAdjustDialog({
  priceListId,
  listName,
  onDone,
}: {
  priceListId: string;
  listName: string;
  onDone: (warnings: readonly Warning[]) => void;
}) {
  const t = useTranslations("pricing.adjust");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const [open, setOpen] = useState(false);
  const [percent, setPercent] = useState("");
  const [scope, setScope] = useState<Scope>("brand");
  const [target, setTarget] = useState("");
  const [includeMissing, setIncludeMissing] = useState(false);
  const [rounding, setRounding] = useState<"PAISA" | "RUPEE">("PAISA");
  const [preview, setPreview] = useState<AdjustPreview | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const body = () => ({
    percent: percent.trim().replace("+", ""),
    category: scope === "category" ? target || null : null,
    brand: scope === "brand" ? target || null : null,
    include_missing: includeMissing,
    rounding,
  });
  const changed = () => setPreview(null);

  async function runPreview() {
    setBusy(true);
    setFieldErrors({});
    try {
      setPreview((await priceListsAdjustPreview(priceListId, body())).data);
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(Object.keys(fields).length ? fields : { percent: errors.message(err) });
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview) return;
    setBusy(true);
    try {
      const response = await priceListsAdjust(priceListId, {
        ...body(),
        expected_count: preview.count,
      });
      toast.success(t("done", { count: response.data.changed }));
      setOpen(false);
      onDone(response.data.warnings);
    } catch (err) {
      setFieldErrors({ percent: errors.message(err) });
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setPreview(null);
          setFieldErrors({});
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-10">
          <Percent aria-hidden />
          {t("open")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title", { list: listName })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <FormField
          label={t("percent")}
          required
          error={fieldErrors.percent}
          hint={t("percentHint")}
        >
          <Input
            inputMode="decimal"
            className="h-10"
            value={percent}
            onChange={(e) => {
              setPercent(e.target.value);
              changed();
            }}
          />
        </FormField>
        <FormField label={t("scope")} required>
          <FormSelect
            value={scope}
            onValueChange={(v) => {
              setScope(v as Scope);
              setTarget("");
              changed();
            }}
            options={[
              { value: "brand", label: t("byBrand") },
              { value: "category", label: t("byCategory") },
            ]}
          />
        </FormField>
        <FormField
          label={scope === "brand" ? t("brand") : t("category")}
          required
          error={fieldErrors.scope ?? fieldErrors.brand ?? fieldErrors.category}
          hint={scope === "category" ? t("categoryHint") : undefined}
        >
          <FormSelect
            value={target}
            onValueChange={(v) => {
              setTarget(v);
              changed();
            }}
            options={scope === "brand" ? brands : categories}
          />
        </FormField>
        <label className="flex items-start gap-3 text-sm">
          <Checkbox
            checked={includeMissing}
            onCheckedChange={(checked) => {
              setIncludeMissing(Boolean(checked));
              changed();
            }}
            className="mt-0.5"
          />
          <span>
            <span className="block font-medium">{t("includeMissing")}</span>
            <span className="text-muted-foreground block">{t("includeMissingHint")}</span>
          </span>
        </label>
        <FormField label={t("rounding")}>
          <FormSelect
            value={rounding}
            onValueChange={(v) => {
              setRounding(v as "PAISA" | "RUPEE");
              changed();
            }}
            options={[
              { value: "PAISA", label: t("paisa") },
              { value: "RUPEE", label: t("rupee") },
            ]}
          />
        </FormField>
        {preview ? (
          <div
            className="bg-muted/50 space-y-2 rounded-lg p-3 text-sm"
            role="region"
            aria-label={t("preview")}
          >
            <p className="font-medium">
              {preview.count
                ? t("summary", { count: preview.count, added: preview.added })
                : t("nothing")}
            </p>
            <ul className="max-h-48 overflow-y-auto">
              {preview.rows.map((row) => (
                <li key={row.code} className="flex justify-between gap-2">
                  <span className="truncate">
                    {row.name} ({row.code})
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {row.old ? (
                      <>
                        <MoneyText value={row.old} className="text-muted-foreground line-through" />{" "}
                        →{" "}
                      </>
                    ) : (
                      <span className="text-muted-foreground">{t("added")} </span>
                    )}
                    <MoneyText value={row.new} className="font-medium" />
                  </span>
                </li>
              ))}
            </ul>
            {preview.count > preview.rows.length ? (
              <p className="text-muted-foreground">
                {t("more", { count: preview.count - preview.rows.length })}
              </p>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {tc("cancel")}
          </Button>
          {preview && preview.count > 0 ? (
            <Button disabled={busy} onClick={() => void apply()}>
              {t("apply", { count: preview.count })}
            </Button>
          ) : (
            <Button disabled={busy || !percent.trim() || !target} onClick={() => void runPreview()}>
              {t("previewButton")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
