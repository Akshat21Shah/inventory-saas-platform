"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ImageOff, Info, TriangleAlert, WifiOff } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { MoneyText } from "@/components/shared/money-text";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, NETWORK_ERROR } from "@/lib/api/errors";
import {
  getShopCartRetrieveQueryKey,
  shopCartClear,
  shopCartReduceToAvailable,
  shopCheckoutAttempt,
  shopOrdersPlace,
  useShopAddressesList,
  useShopCartRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { Problem, Quote, QuoteLine } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { attemptFor, finishAttempt, pendingAttempt } from "@/lib/checkout";
import { formatMoney, formatQty } from "@/lib/format";
import { idempotent } from "@/lib/idempotency";
import { useIsCompact } from "@/lib/use-media";
import { cn } from "@/lib/utils";

import { OnHoldNotice } from "./catalog";
import { useCart } from "./cart-state";
import { QuantityStepper } from "./quantity-stepper";

/** A problem from the server in plain words (codes from apps/orders/quote.py), worded for the
 * shop, or for staff ordering on its behalf. */
export function ProblemText({
  problem,
  unit,
  audience = "shop",
}: {
  problem: Problem;
  unit?: string;
  audience?: "shop" | "staff";
}) {
  const t = useTranslations(
    audience === "shop" ? "shop.cart.problems" : "orders.onBehalf.problems",
  );
  const d = problem.details as Record<string, string | undefined>;
  const qty = (value?: string) => (value ? formatQty(value) : "");
  switch (problem.code) {
    case "QTY_BELOW_MINIMUM":
      return <>{t("QTY_BELOW_MINIMUM", { qty: qty(d.minimum), unit: unit ?? "" })}</>;
    case "QTY_NOT_MULTIPLE":
      return <>{t("QTY_NOT_MULTIPLE", { qty: qty(d.step) })}</>;
    case "NOT_ENOUGH_STOCK":
    case "PARTLY_AVAILABLE":
      return <>{t(problem.code, { qty: qty(d.available), unit: unit ?? "" })}</>;
    case "MIN_ORDER_VALUE":
      return (
        <>
          {t(d.basis === "INCL_GST" ? "MIN_ORDER_VALUE" : "MIN_ORDER_VALUE_EXCL", {
            amount: d.minimum ? formatMoney(d.minimum) : "",
          })}
        </>
      );
    case "CREDIT_LIMIT_EXCEEDED":
      return <>{t("CREDIT_LIMIT_EXCEEDED", { amount: formatMoney(d.available ?? "0") })}</>;
    default:
      return <>{t.has(problem.code) ? t(problem.code) : t("OTHER")}</>;
  }
}

function Notice({
  tone,
  children,
}: {
  tone: "warning" | "info" | "danger";
  children: React.ReactNode;
}) {
  const Icon = tone === "info" ? Info : TriangleAlert;
  return (
    <p
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex gap-2 rounded-xl p-3 text-sm",
        tone === "warning" && "bg-warning/15",
        tone === "info" && "bg-info/10",
        tone === "danger" && "bg-destructive/10",
      )}
    >
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function CartLine({ line }: { line: QuoteLine }) {
  const t = useTranslations("shop.cart");
  const product = line.product;
  if (!product) {
    return (
      <li className="rounded-xl border p-3 text-sm">
        <p>{t("gone")}</p>
      </li>
    );
  }
  const later = line.later_qty !== "0.000";
  return (
    <li className="space-y-2 rounded-xl border p-3">
      <div className="flex gap-3">
        {product.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image
          <img
            src={product.thumbnail_url}
            alt=""
            className="bg-muted size-16 shrink-0 rounded-lg object-contain"
          />
        ) : (
          <span className="bg-muted text-muted-foreground flex size-16 shrink-0 items-center justify-center rounded-lg">
            <ImageOff aria-hidden className="size-5" />
          </span>
        )}
        <div className="min-w-0 flex-1 space-y-0.5">
          <Link href={`/shop/products/${product.id}`} className="font-medium hover:underline">
            {product.name}
          </Link>
          {line.unit_price ? (
            <p className="text-muted-foreground text-xs">
              <MoneyText value={line.unit_price} /> {t("each")}
              {line.discount_total && line.discount_total !== "0.00" ? (
                <>
                  {" · "}
                  <span className="text-success-strong">
                    {t("saving", { amount: formatMoney(line.discount_total) })}
                  </span>
                </>
              ) : null}
            </p>
          ) : null}
          {later ? (
            <p className="text-info-strong text-xs">
              {line.ready_qty !== "0.000"
                ? t("splitNowLater", {
                    now: formatQty(line.ready_qty),
                    later: formatQty(line.later_qty),
                    unit: product.unit.name,
                  })
                : t("allLater")}
            </p>
          ) : null}
        </div>
        {line.line_total ? (
          <MoneyText value={line.line_total} className="shrink-0 font-semibold" />
        ) : null}
      </div>
      <div className="flex justify-end">
        <QuantityStepper product={{ ...product, unit: product.unit }} className="w-44 max-w-full" />
      </div>
      {line.problems.map((problem) => (
        <p
          key={problem.code}
          className={cn("text-sm", problem.blocking ? "text-destructive" : "text-warning-strong")}
        >
          <ProblemText problem={problem} unit={product.unit.name} />
        </p>
      ))}
    </li>
  );
}

function Totals({ quote }: { quote: Quote }) {
  const t = useTranslations("shop.cart");
  const x = quote.totals;
  const row = (label: string, value: string, strong = false) => (
    <div className={cn("flex justify-between gap-4", strong && "text-base font-semibold")}>
      <dt>{label}</dt>
      <dd>
        <MoneyText value={value} />
      </dd>
    </div>
  );
  return (
    <dl className="space-y-1 text-sm">
      {row(t("itemsTotal"), x.gross)}
      {x.discount !== "0.00" ? row(t("discount"), `-${x.discount}`) : null}
      {row(t("gst"), x.tax)}
      {x.round_off !== "0.00" ? row(t("roundOff"), x.round_off) : null}
      {row(t("total"), x.grand_total, true)}
      <p className="text-muted-foreground text-xs">{t("estimate")}</p>
    </dl>
  );
}

type Stage =
  | { kind: "idle" }
  | { kind: "placing" }
  | { kind: "checking" }
  | { kind: "unknown" } // the connection dropped: we don't know if it went through
  | { kind: "offline" }; // couldn't even ask

/** Cart and one-screen checkout (ADR-044): what can be sent now and what later, problems to fix,
 * the delivery address and instructions, the server's totals, and "Place order". */
export function CartPage() {
  const t = useTranslations("shop.cart");
  const router = useRouter();
  const client = useQueryClient();
  const { me } = useAuth();
  const { message } = useErrorText();
  const { pending, version } = useCart();
  const [address, setAddress] = useState<string | undefined>(undefined);
  const [note, setNote] = useState("");
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const owner = me?.id ?? "anon";
  const query = useShopCartRetrieve(address ? { address } : undefined);
  const addresses = useShopAddressesList();
  const quote = query.data?.data;
  const checkedLeftover = useRef(false);
  const compact = useIsCompact();

  const placed = (orderId: string) => {
    finishAttempt(owner);
    void client.invalidateQueries({
      predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/v1/shop/"),
    });
    router.push(`/shop/orders/${orderId}?placed=1`);
  };

  /** After a reload in the middle of a checkout: did it go through? */
  useEffect(() => {
    if (checkedLeftover.current || !me) return;
    checkedLeftover.current = true;
    const leftover = pendingAttempt(owner);
    if (!leftover) return;
    shopCheckoutAttempt(leftover.key)
      .then(({ data }) => {
        if (data.status === "placed" && data.order) placed(data.order);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the user is known
  }, [me]);

  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !quote) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (quote.lines.length === 0) {
    return (
      <EmptyState
        title={t("emptyTitle")}
        description={t("emptyBody")}
        action={
          <Button asChild className="min-h-11">
            <Link href="/shop/catalog">{t("browse")}</Link>
          </Button>
        }
      />
    );
  }

  const ready = quote.lines.filter((l) => l.later_qty === "0.000");
  const later = quote.lines.filter((l) => l.later_qty !== "0.000");
  const orderProblems = quote.problems.filter((p) => p.code !== "CREDIT_APPROVAL_NEEDED");
  const needsApproval = quote.problems.some((p) => p.code === "CREDIT_APPROVAL_NEEDED");
  const canReduce = quote.lines.some((l) => l.problems.some((p) => p.code === "NOT_ENOUGH_STOCK"));
  const busy = stage.kind === "placing" || stage.kind === "checking";

  const submit = async () => {
    setError(null);
    const attempt = attemptFor(owner, `${version}|${quote.address_id ?? ""}|${note.trim()}`);
    try {
      if (stage.kind === "unknown" || stage.kind === "offline") {
        // Ask first: the last try may have gone through.
        setStage({ kind: "checking" });
        const { data } = await shopCheckoutAttempt(attempt.key);
        if (data.status === "placed" && data.order) return placed(data.order);
      }
      setStage({ kind: "placing" });
      const response = await shopOrdersPlace(
        {
          expected_total: quote.expected_total,
          address: quote.address_id ?? null,
          note: note.trim(),
        },
        idempotent(attempt.key),
      );
      placed(response.data.id);
    } catch (thrown) {
      if (thrown instanceof ApiError && thrown.code === NETWORK_ERROR) {
        setStage({
          kind: stage.kind === "idle" || stage.kind === "placing" ? "unknown" : "offline",
        });
        return;
      }
      setStage({ kind: "idle" });
      setError(message(thrown));
      if (thrown instanceof ApiError && ["PRICE_CHANGED", "CART_NOT_READY"].includes(thrown.code)) {
        void query.refetch();
      }
    }
  };

  const placeButton = (
    <Button
      className="min-h-12 w-full text-base"
      disabled={!quote.can_place || pending || busy}
      onClick={() => void submit()}
    >
      {stage.kind === "placing"
        ? t("placing")
        : stage.kind === "checking"
          ? t("checking")
          : stage.kind === "unknown" || stage.kind === "offline"
            ? t("tryAgain")
            : t("place", { total: formatMoney(quote.totals.grand_total) })}
    </Button>
  );

  return (
    <div className={cn("space-y-5", compact ? "pb-24" : "pb-4")}>
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <OnHoldNotice />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem] lg:items-start">
        <div className="space-y-5">
          {ready.length ? (
            <section className="space-y-2" aria-labelledby="ready-heading">
              <h2 id="ready-heading" className="font-semibold">
                {t("readyTitle", { count: ready.length })}
              </h2>
              <ul className="space-y-2">
                {ready.map((line) => (
                  <CartLine key={line.product_id} line={line} />
                ))}
              </ul>
            </section>
          ) : null}
          {later.length ? (
            <section className="space-y-2" aria-labelledby="later-heading">
              <h2 id="later-heading" className="font-semibold">
                {quote.backorders_enabled ? t("laterTitle") : t("shortTitle")}
              </h2>
              <p className="text-muted-foreground text-sm">
                {quote.backorders_enabled ? t("laterBody") : t("shortBody")}
              </p>
              <ul className="space-y-2">
                {later.map((line) => (
                  <CartLine key={line.product_id} line={line} />
                ))}
              </ul>
              {canReduce ? (
                <Button
                  variant="outline"
                  className="min-h-11"
                  onClick={async () => {
                    const response = await shopCartReduceToAvailable();
                    client.setQueryData(getShopCartRetrieveQueryKey(), response);
                    void query.refetch();
                  }}
                >
                  {t("reduce")}
                </Button>
              ) : null}
            </section>
          ) : null}
        </div>

        <section
          className="space-y-4 rounded-xl border p-4 lg:sticky lg:top-20"
          aria-labelledby="checkout-heading"
        >
          <h2 id="checkout-heading" className="font-semibold">
            {t("checkoutTitle")}
          </h2>
          {(addresses.data?.data.length ?? 0) > 1 ? (
            <div className="space-y-1.5">
              <Label htmlFor="address">{t("deliverTo")}</Label>
              <select
                id="address"
                className="border-input bg-background h-11 w-full rounded-md border px-3 text-base"
                value={quote.address_id ?? ""}
                onChange={(e) => setAddress(e.target.value || undefined)}
              >
                {addresses.data?.data.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name || a.line1}, {a.city}
                  </option>
                ))}
              </select>
            </div>
          ) : addresses.data?.data[0] ? (
            <p className="text-sm">
              <span className="text-muted-foreground">{t("deliverTo")}: </span>
              {addresses.data.data[0].line1}, {addresses.data.data[0].city}
            </p>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="note">{t("noteLabel")}</Label>
            <Textarea
              id="note"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("notePlaceholder")}
              className="min-h-20 text-base"
            />
          </div>
          <Totals quote={quote} />
          {orderProblems.map((problem) => (
            <Notice key={problem.code} tone={problem.blocking ? "danger" : "warning"}>
              <ProblemText problem={problem} />
            </Notice>
          ))}
          {needsApproval ? <Notice tone="info">{t("needsApproval")}</Notice> : null}
          {stage.kind === "unknown" ? <Notice tone="warning">{t("unknownOutcome")}</Notice> : null}
          {stage.kind === "offline" ? (
            <p role="alert" className="bg-destructive/10 flex gap-2 rounded-xl p-3 text-sm">
              <WifiOff aria-hidden className="mt-0.5 size-4 shrink-0" />
              {t("offline")}
            </p>
          ) : null}
          {error ? <Notice tone="danger">{error}</Notice> : null}
          {compact ? null : placeButton}
          <ConfirmDialog
            trigger={
              <Button variant="ghost" className="min-h-11 w-full" disabled={busy}>
                {t("clear")}
              </Button>
            }
            title={t("clearTitle")}
            confirmLabel={t("clear")}
            destructive
            onConfirm={async () => {
              const response = await shopCartClear();
              client.setQueryData(getShopCartRetrieveQueryKey(), response);
              void query.refetch();
            }}
          />
        </section>
      </div>
      {compact ? (
        // Phones and tablets: the total and "Place order" stay in reach above the navigation.
        <div className="bg-background fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 border-t px-4 py-2">
          <div className="mx-auto max-w-4xl">{placeButton}</div>
        </div>
      ) : null}
    </div>
  );
}
