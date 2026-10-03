"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleCheck, PackageCheck, RotateCcw, Truck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { DocumentButton } from "@/components/billing/document-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { OrderStatus } from "@/components/shared/order-status";
import { OrderTimeline } from "@/components/shared/order-timeline";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { FreeLineLabel } from "@/components/shop/free-goods";
import {
  getShopCartRetrieveQueryKey,
  getShopOrderQueryKey,
  shopFulfilmentLineCancelRepriced,
  shopFulfilmentReceived,
  shopOrderCancel,
  shopOrderLineCancelBackorder,
  shopOrderRepeat,
  shopOrdersConfirmation,
  shopOrdersList,
  useShopOrder,
} from "@/lib/api/generated/endpoints/shop/shop";
import type {
  OrderLine,
  ShopFulfilment,
  ShopOrder,
  ShopOrdersListState,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney, formatQty } from "@/lib/format";
import { fromMilli, toMilli } from "@/lib/qty";
import { cn } from "@/lib/utils";

import { OrderRowLink } from "./home";

function cursorOf(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return new URL(url, "http://localhost").searchParams.get("cursor") ?? undefined;
}

export function OrdersPage() {
  const t = useTranslations("shop.orders");
  const [state, setState] = useState<ShopOrdersListState>("open");
  const query = useInfiniteQuery({
    queryKey: ["/api/v1/shop/orders/", "infinite", state],
    queryFn: ({ pageParam }) => shopOrdersList({ state, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.data.next),
  });
  const orders = query.data?.pages.flatMap((p) => p.data.results) ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <div role="tablist" aria-label={t("show")} className="flex gap-2">
        {(["open", "closed"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={state === value}
            onClick={() => setState(value)}
            className={cn(
              "min-h-11 rounded-full border px-4 text-sm",
              state === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
            )}
          >
            {t(value)}
          </button>
        ))}
      </div>
      {query.isLoading ? (
        <div className="space-y-2">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : orders.length === 0 ? (
        <EmptyState
          title={state === "open" ? t("noneOpen") : t("noneClosed")}
          description={t("noneBody")}
          action={
            <Button asChild className="min-h-11">
              <Link href="/shop/catalog">{t("browse")}</Link>
            </Button>
          }
        />
      ) : (
        <>
          <ul className="space-y-2">
            {orders.map((order) => (
              <OrderRowLink key={order.id} order={order} />
            ))}
          </ul>
          {query.hasNextPage ? (
            <Button
              variant="outline"
              className="min-h-11 w-full"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {t("showMore")}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}

/** Where each item of the order is, in words the shop uses. */
function LineState({ line }: { line: OrderLine }) {
  const t = useTranslations("shop.orders.line");
  const parts: string[] = [];
  const q = (v: string) => formatQty(v);
  if (line.qty_delivered !== "0.000") parts.push(t("delivered", { qty: q(line.qty_delivered) }));
  const onTheWay = (toMilli(line.qty_dispatched) ?? 0) - (toMilli(line.qty_delivered) ?? 0);
  if (onTheWay > 0) parts.push(t("onTheWay", { qty: formatQty(fromMilli(onTheWay)) }));
  if (line.ready_qty !== "0.000" && line.ready_qty !== "0") {
    parts.push(t("ready", { qty: q(line.ready_qty) }));
  }
  if (line.qty_pending !== "0.000") parts.push(t("pending", { qty: q(line.qty_pending) }));
  if (line.qty_backordered !== "0.000") parts.push(t("waiting", { qty: q(line.qty_backordered) }));
  if (line.qty_cancelled !== "0.000") parts.push(t("cancelled", { qty: q(line.qty_cancelled) }));
  return <p className="text-muted-foreground text-xs">{parts.join(" · ")}</p>;
}

function useRefresh(orderId: string) {
  const client = useQueryClient();
  return (response: { data: ShopOrder }) => {
    client.setQueryData(getShopOrderQueryKey(orderId), response);
    void client.invalidateQueries({
      predicate: (q) => {
        const key = String(q.queryKey[0] ?? "");
        return key === "/api/v1/shop/orders/" || key.startsWith("/api/v1/shop/home");
      },
    });
  };
}

function Lines({ order }: { order: ShopOrder }) {
  const t = useTranslations("shop.orders");
  const refresh = useRefresh(order.id);
  const waitingAllowed = ["ACCEPTED", "PACKED", "DISPATCHED", "PARTLY_DELIVERED"].includes(
    order.status,
  );
  return (
    <section className="space-y-2" aria-labelledby="items-heading">
      <h2 id="items-heading" className="font-semibold">
        {t("itemsTitle")}
      </h2>
      <ul className="divide-y rounded-xl border">
        {order.lines.map((line) => (
          <li key={line.id} className="space-y-1 p-3">
            <div className="flex justify-between gap-3">
              <span className="min-w-0">
                <span className="block font-medium">{line.product_name}</span>
                {line.free_of_line ? <FreeLineLabel scheme={line.scheme_name} /> : null}
                <span className="text-muted-foreground block text-xs">
                  {formatQty(line.qty_ordered)} {line.unit_code} ×{" "}
                  <MoneyText value={line.unit_price} />
                </span>
              </span>
              <MoneyText value={line.line_total} className="shrink-0 font-medium" />
            </div>
            <LineState line={line} />
            {waitingAllowed && line.qty_backordered !== "0.000" ? (
              <ConfirmDialog
                trigger={
                  <Button variant="outline" size="sm" className="min-h-11">
                    {t("cancelWaiting")}
                  </Button>
                }
                title={t("cancelWaitingTitle", { name: line.product_name })}
                description={t("cancelWaitingBody", { qty: formatQty(line.qty_backordered) })}
                confirmLabel={t("cancelWaiting")}
                destructive
                onConfirm={async () => refresh(await shopOrderLineCancelBackorder(line.id))}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The order's bills and its Order Confirmation, to download (Phase 5). */
function OrderDocuments({ order }: { order: ShopOrder }) {
  const t = useTranslations("shop.orders");
  if (!order.invoices.length && !order.has_confirmation) return null;
  return (
    <section className="space-y-2 border-b pb-4" aria-labelledby="order-documents">
      <h2 id="order-documents" className="font-semibold">
        {t("documents")}
      </h2>
      {order.invoices.length ? (
        <ul className="divide-y text-sm">
          {order.invoices.map((bill) => (
            <li key={bill.id}>
              <Link
                href={`/shop/invoices/${bill.id}`}
                className="flex min-h-11 items-center justify-between gap-2"
              >
                <span className="font-medium">{bill.number}</span>
                <MoneyText value={bill.grand_total} />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {order.has_confirmation ? (
        <DocumentButton fetchLink={() => shopOrdersConfirmation(order.id)}>
          {t("confirmation")}
        </DocumentButton>
      ) : null}
    </section>
  );
}

function Shipment({ order, shipment }: { order: ShopOrder; shipment: ShopFulfilment }) {
  const t = useTranslations("shop.orders");
  const refresh = useRefresh(order.id);
  const onItsWay = shipment.status === "DISPATCHED";
  return (
    <li className="space-y-2 rounded-xl border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium">
          <Truck aria-hidden className="size-4" />
          {shipment.number}
        </span>
        <StatusBadge status={shipment.status} labels="shipmentStatus" />
      </div>
      {shipment.dispatched_at ? (
        <p className="text-muted-foreground text-xs">
          {t("sentOn")} <DateText value={shipment.dispatched_at} withTime />
          {shipment.vehicle_number ? ` · ${shipment.vehicle_number}` : ""}
        </p>
      ) : null}
      {onItsWay && shipment.delivery_code ? (
        <div className="bg-info/10 rounded-lg p-3 text-sm">
          <p>{t("codeIntro")}</p>
          <p
            className="text-2xl font-semibold tracking-[0.3em] tabular-nums"
            aria-label={t("codeLabel", { code: shipment.delivery_code.split("").join(" ") })}
          >
            {shipment.delivery_code}
          </p>
        </div>
      ) : null}
      {onItsWay && shipment.can_confirm ? (
        <ConfirmDialog
          trigger={
            <Button className="min-h-11 w-full sm:w-auto">
              <PackageCheck aria-hidden />
              {t("received")}
            </Button>
          }
          title={t("receivedTitle", { number: shipment.number })}
          description={t("receivedBody")}
          confirmLabel={t("received")}
          onConfirm={async () => refresh(await shopFulfilmentReceived(shipment.id))}
        />
      ) : null}
      <ul className="space-y-1 text-sm">
        {shipment.lines.map((line) => (
          <li key={line.id} className="space-y-1">
            <span className={cn(line.cancelled_by_retailer_at && "line-through")}>
              {line.product_name}: {formatQty(line.qty_packed ?? line.quantity)} {line.unit_code}
            </span>
            {line.price_increased && !line.cancelled_by_retailer_at ? (
              <div className="bg-warning/15 space-y-2 rounded-lg p-2 text-xs">
                <p>
                  {t("priceUp", {
                    before: formatMoney(line.ordered_price),
                    now: formatMoney(line.unit_price),
                  })}
                </p>
                {shipment.status === "ALLOCATED" ? (
                  <ConfirmDialog
                    trigger={
                      <Button variant="outline" size="sm" className="min-h-11">
                        {t("decline")}
                      </Button>
                    }
                    title={t("declineTitle", { name: line.product_name })}
                    description={t("declineBody")}
                    confirmLabel={t("decline")}
                    destructive
                    onConfirm={async () => refresh(await shopFulfilmentLineCancelRepriced(line.id))}
                  />
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </li>
  );
}

export function OrderPage({ orderId }: { orderId: string }) {
  const t = useTranslations("shop.orders");
  const params = useSearchParams();
  const router = useRouter();
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopOrder(orderId);
  const refresh = useRefresh(orderId);
  const [repeating, setRepeating] = useState(false);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return (
      <EmptyState
        title={t("goneTitle")}
        action={
          <Button asChild className="min-h-11">
            <Link href="/shop/orders">{t("title")}</Link>
          </Button>
        }
      />
    );
  }
  const order = query.data.data;
  const justPlaced = params.get("placed") === "1";
  const cancellable = order.status === "PLACED" || order.status === "ON_HOLD";

  const repeat = async () => {
    setRepeating(true);
    try {
      const response = await shopOrderRepeat(order.id);
      client.setQueryData(getShopCartRetrieveQueryKey(), {
        ...response,
        data: response.data.cart,
      });
      if (response.data.skipped.length) {
        toast(t("skipped", { count: response.data.skipped.length }));
      }
      router.push("/shop/cart");
    } catch (error) {
      toast.error(message(error));
      setRepeating(false);
    }
  };

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" className="-ml-3 min-h-11">
        <Link href="/shop/orders">
          <ArrowLeft aria-hidden />
          {t("title")}
        </Link>
      </Button>
      {justPlaced ? (
        <p role="status" className="bg-success/12 flex gap-2 rounded-xl p-4">
          <CircleCheck aria-hidden className="text-success-strong mt-0.5 size-5 shrink-0" />
          <span>
            <span className="block font-semibold">{t("placedTitle")}</span>
            <span className="text-sm">{t("placedBody")}</span>
          </span>
        </p>
      ) : null}
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{order.number}</h1>
        <OrderStatus status={order.status} itemsToFollow={order.items_to_follow} />
        <p className="text-muted-foreground text-sm">
          <DateText value={order.placed_at} withTime />
          {order.placed_by_label ? ` · ${t("placedBy", { name: order.placed_by_label })}` : ""}
        </p>
      </div>
      {order.status === "ON_HOLD" ? (
        <p className="bg-warning/15 rounded-xl p-3 text-sm">
          {t(order.hold_reason === "OVERDUE" ? "onHoldOverdue" : "onHold")}
        </p>
      ) : null}
      {order.rejection_reason ? (
        <p className="bg-destructive/10 rounded-xl p-3 text-sm">
          {t("rejectedBecause", { reason: order.rejection_reason })}
        </p>
      ) : null}
      {order.status === "CANCELLED" && order.cancellation_reason ? (
        <p className="bg-muted rounded-xl p-3 text-sm">
          {t("cancelledBecause", { reason: order.cancellation_reason })}
        </p>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem] lg:items-start">
        <div className="space-y-5">
          <Lines order={order} />
          {order.fulfilments.length ? (
            <section className="space-y-2" aria-labelledby="shipments-heading">
              <h2 id="shipments-heading" className="font-semibold">
                {t("shipmentsTitle")}
              </h2>
              <ul className="space-y-2">
                {order.fulfilments.map((shipment) => (
                  <Shipment key={shipment.id} order={order} shipment={shipment} />
                ))}
              </ul>
            </section>
          ) : null}
          <section className="space-y-3" aria-labelledby="timeline-heading">
            <h2 id="timeline-heading" className="font-semibold">
              {t("timelineTitle")}
            </h2>
            <OrderTimeline entries={order.history} />
          </section>
        </div>
        <aside className="space-y-4 rounded-xl border p-4">
          <OrderDocuments order={order} />
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between">
              <dt>{t("gst")}</dt>
              <dd>
                <MoneyText value={order.tax_total} />
              </dd>
            </div>
            <div className="flex justify-between text-base font-semibold">
              <dt>{t("total")}</dt>
              <dd>
                <MoneyText value={order.grand_total} />
              </dd>
            </div>
          </dl>
          {order.retailer_note ? (
            <p className="text-sm">
              <span className="text-muted-foreground">{t("note")}: </span>
              {order.retailer_note}
            </p>
          ) : null}
          <Button
            variant="outline"
            className="min-h-11 w-full gap-2"
            disabled={repeating}
            onClick={() => void repeat()}
          >
            <RotateCcw aria-hidden className="size-4" />
            {t("orderAgain")}
          </Button>
          {cancellable ? (
            <ConfirmDialog
              trigger={
                <Button variant="ghost" className="text-destructive min-h-11 w-full">
                  {t("cancel")}
                </Button>
              }
              title={t("cancelTitle", { number: order.number })}
              description={t("cancelBody")}
              confirmLabel={t("cancel")}
              destructive
              onConfirm={async () => refresh(await shopOrderCancel(order.id, { reason: "" }))}
            />
          ) : null}
        </aside>
      </div>
    </div>
  );
}
