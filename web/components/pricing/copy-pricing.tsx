"use client";

import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/shared/form-field";
import { MoneyText } from "@/components/shared/money-text";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  retailersCopyPricing,
  retailersCopyPricingPreview,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import type { CopyModeEnum, CopyPlan, PriceChange } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { cn } from "@/lib/utils";

import { RetailerPicker, type Picked } from "./pickers";

function Changes({ title, rows }: { title: string; rows: PriceChange[] }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <p className="font-medium">{title}</p>
      <ul className="text-muted-foreground max-h-32 overflow-y-auto">
        {rows.map((r) => (
          <li key={r.code}>
            {r.name} ({r.code}):{" "}
            {r.old && r.old !== r.new ? (
              <>
                <MoneyText value={r.old} className="line-through" /> →{" "}
              </>
            ) : null}
            <MoneyText value={r.new} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function Names({ title, names }: { title: string; names: string[] }) {
  if (names.length === 0) return null;
  return (
    <div>
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground">{names.join(", ")}</p>
    </div>
  );
}

export function CopyPricingDialog({
  retailerId,
  shopName,
  onCopied,
}: {
  retailerId: string;
  shopName: string;
  onCopied: () => void;
}) {
  const t = useTranslations("pricing.copy");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState<Picked | null>(null);
  // No default: the user chooses Replace or Add every time (ADR-037).
  const [mode, setMode] = useState<CopyModeEnum | "">("");
  const [plan, setPlan] = useState<CopyPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reset() {
    setFrom(null);
    setMode("");
    setPlan(null);
    setError(null);
  }

  async function preview() {
    if (!from || !mode) return;
    setBusy(true);
    setError(null);
    try {
      const response = await retailersCopyPricingPreview(retailerId, { copy_from: from.id, mode });
      setPlan(response.data);
    } catch (err) {
      const fields = errors.fields(err);
      setError(fields.copy_from ?? fields.mode ?? errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!from || !mode || !plan) return;
    setBusy(true);
    try {
      await retailersCopyPricing(retailerId, {
        copy_from: from.id,
        mode,
        expected_changes: plan.changes,
      });
      toast.success(t("done"));
      setOpen(false);
      onCopied();
    } catch (err) {
      setError(errors.message(err));
      setPlan(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-10">
          <Copy aria-hidden />
          {t("open")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title", { shop: shopName })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <FormField label={t("from")} required>
          <RetailerPicker
            value={from}
            onChange={(next) => {
              setFrom(next);
              setPlan(null);
            }}
          />
        </FormField>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">{t("modeTitle")}</legend>
          {(["REPLACE", "ADD"] as const).map((value) => (
            <label
              key={value}
              className={cn(
                "flex min-h-11 cursor-pointer gap-3 rounded-lg border p-3",
                mode === value ? "border-brand-400 bg-brand-50" : "hover:bg-muted",
              )}
            >
              <input
                type="radio"
                name="copy-mode"
                value={value}
                checked={mode === value}
                onChange={() => {
                  setMode(value);
                  setPlan(null);
                }}
                className="accent-brand-600 mt-1 size-4"
              />
              <span>
                <span className="block font-medium">{t(`mode.${value}`)}</span>
                <span className="text-muted-foreground block text-sm">
                  {t(`modeHint.${value}`)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        {plan ? (
          <div
            className="bg-muted/50 space-y-3 rounded-lg p-3 text-sm"
            role="region"
            aria-label={t("preview")}
          >
            {plan.changes === 0 ? (
              <p>{t("nothing")}</p>
            ) : (
              <>
                {plan.price_list_changes ? (
                  <p>
                    {t("priceList", {
                      from: plan.price_list_from ?? t("standard"),
                      to: plan.price_list_to ?? t("standard"),
                    })}
                  </p>
                ) : null}
                <Changes title={t("pricesAdd")} rows={plan.prices_add} />
                <Changes title={t("pricesUpdate")} rows={plan.prices_update} />
                <Changes title={t("pricesRemove")} rows={plan.prices_remove} />
                <Names title={t("rulesAdd")} names={plan.rules_add} />
                <Names title={t("rulesReplace")} names={plan.rules_replace} />
                <Names title={t("rulesRemove")} names={plan.rules_remove} />
              </>
            )}
          </div>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {tc("cancel")}
          </Button>
          {plan && plan.changes > 0 ? (
            <Button disabled={busy} onClick={() => void apply()}>
              {t("apply", { count: plan.changes })}
            </Button>
          ) : (
            <Button disabled={busy || !from || !mode} onClick={() => void preview()}>
              {t("previewButton")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
