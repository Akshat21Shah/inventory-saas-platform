"use client";

import { Gift } from "lucide-react";
import { useTranslations } from "next-intl";

import type { FreeOffer, SchemeTerms } from "@/lib/api/generated/model";
import { formatQty } from "@/lib/format";
import { cn } from "@/lib/utils";

/** "Buy 10, get 1 free" or "Buy 6, get 1 Lizol Floor Cleaner free": the server's scheme in plain
 * words (ADR-056 item 8; the server decides what is free). */
export function useOfferText() {
  const t = useTranslations("shop.free");
  return (
    offer: Pick<SchemeTerms, "buy_qty" | "free_qty" | "same_product" | "free_product_name">,
  ) =>
    t("offer", {
      same: String(offer.same_product),
      buy: formatQty(offer.buy_qty),
      free: formatQty(offer.free_qty),
      product: offer.free_product_name,
    });
}

export function FreeOfferBadge({ offer, className }: { offer: SchemeTerms; className?: string }) {
  const text = useOfferText();
  return (
    <span
      className={cn(
        "bg-success/12 text-success-strong inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <Gift aria-hidden className="size-3.5" />
      {text(offer)}
    </span>
  );
}

/** The scheme on a product's page: what is free, how often, and the most on one order. */
export function FreeOfferDetails({ offer }: { offer: SchemeTerms }) {
  const t = useTranslations("shop.free");
  const text = useOfferText();
  return (
    <section className="bg-success/10 space-y-1 rounded-xl p-4">
      <h2 className="flex items-center gap-2 font-semibold">
        <Gift aria-hidden className="size-4" />
        {text(offer)}
      </h2>
      <p className="text-sm">
        {offer.repeat ? t("every", { buy: formatQty(offer.buy_qty) }) : t("once")}
        {offer.max_free_qty ? ` ${t("cap", { max: formatQty(offer.max_free_qty) })}` : ""}
      </p>
    </section>
  );
}

/** Under a bought line in a cart: "Add 2 more to get 1 free". */
export function OfferHint({ offer }: { offer: FreeOffer | null }) {
  const t = useTranslations("shop.free");
  if (!offer) return null;
  return (
    <p className="text-success-strong flex items-center gap-1 text-xs font-medium">
      <Gift aria-hidden className="size-3.5 shrink-0" />
      {t("addMore", { qty: formatQty(offer.add_qty), free: formatQty(offer.free_qty) })}
    </p>
  );
}

/** A free line's label: "Free" and the scheme it came with. */
export function FreeLineLabel({ scheme }: { scheme: string }) {
  const t = useTranslations("shop.free");
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="bg-success/12 text-success-strong inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium">
        <Gift aria-hidden className="size-3.5" />
        {t("badge")}
      </span>
      {scheme ? (
        <span className="text-muted-foreground text-xs">{t("under", { scheme })}</span>
      ) : null}
    </span>
  );
}
