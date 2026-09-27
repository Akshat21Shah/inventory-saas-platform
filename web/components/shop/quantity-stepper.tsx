"use client";

import { Minus, Plus, ShoppingCart } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { formatQty } from "@/lib/format";
import { firstQty, isZero, nextQty, previousQty, toMilli } from "@/lib/qty";
import { cn } from "@/lib/utils";

import { useCart } from "./cart-state";

export interface Orderable {
  id: string;
  name: string;
  min_order_qty: string;
  order_multiple: string;
  unit: { name: string };
}

/** The shop's stepper, bound to its cart: taps show at once; the cart on the server follows
 * (cart-state). */
export function QuantityStepper(props: {
  product: Orderable;
  disabled?: boolean;
  className?: string;
  /** Full-width "Add" (product page). */
  wide?: boolean;
}) {
  const { quantityOf, setQuantity } = useCart();
  return (
    <StepperControl
      {...props}
      qty={quantityOf(props.product.id)}
      onSet={(quantity) => setQuantity(props.product.id, quantity)}
    />
  );
}

/** "Add" until there is a quantity, then − quantity + (the quantity can also be typed). Steps
 * start at the product's minimum and follow its multiple; the server still checks. */
export function StepperControl({
  product,
  qty,
  onSet,
  disabled,
  className,
  wide,
}: {
  product: Orderable;
  qty: string;
  onSet: (quantity: string) => void;
  disabled?: boolean;
  className?: string;
  wide?: boolean;
}) {
  const t = useTranslations("shop.order");
  // What the shop is typing, for the quantity it started from (a new quantity replaces it).
  const [draft, setDraft] = useState<{ text: string; from: string } | null>(null);
  const typed = draft && draft.from === qty ? draft.text : null;
  const { min_order_qty: min, order_multiple: multiple } = product;

  if (isZero(qty)) {
    return (
      <Button
        type="button"
        disabled={disabled}
        className={cn("min-h-11 gap-2", wide ? "w-full" : "min-w-24", className)}
        aria-label={t("addNamed", { name: product.name })}
        onClick={() => onSet(firstQty(min, multiple))}
      >
        <ShoppingCart aria-hidden className="size-4" />
        {t("add")}
      </Button>
    );
  }

  const commit = (event?: FormEvent) => {
    event?.preventDefault();
    if (typed === null) return;
    const value = typed.trim() === "" ? "0" : typed.trim();
    setDraft(null);
    if (toMilli(value) === null) return;
    onSet(value);
  };

  return (
    <form
      onSubmit={commit}
      className={cn("flex items-center gap-1", wide && "w-full", className)}
      aria-label={t("quantityOf", { name: product.name })}
    >
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="size-11 shrink-0"
        aria-label={t("less", { name: product.name })}
        onClick={() => onSet(previousQty(qty, min, multiple))}
      >
        <Minus aria-hidden />
      </Button>
      <input
        inputMode="decimal"
        className="border-input bg-background h-11 w-16 min-w-0 flex-1 rounded-md border text-center text-base font-semibold tabular-nums"
        aria-label={t("quantityOf", { name: product.name })}
        value={typed ?? formatQty(qty).replace(/,/g, "")}
        onChange={(e) => setDraft({ text: e.target.value, from: qty })}
        onBlur={() => commit()}
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="size-11 shrink-0"
        aria-label={t("more", { name: product.name })}
        disabled={disabled}
        onClick={() => onSet(nextQty(qty, min, multiple))}
      >
        <Plus aria-hidden />
      </Button>
      <span className="sr-only" aria-live="polite">
        {t("inCart", { qty: formatQty(qty), unit: product.unit.name })}
      </span>
    </form>
  );
}
