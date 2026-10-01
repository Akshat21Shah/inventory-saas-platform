"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Truck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { OrderStatus } from "@/components/shared/order-status";
import { OrderTimeline } from "@/components/shared/order-timeline";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  fulfilmentsCancel,
  fulfilmentsDeliver,
  fulfilmentsDispatch,
  fulfilmentsPack,
  getOrdersRetrieveQueryKey,
  orderLinesCancelBackorder,
  ordersAccept,
  ordersCancel,
  ordersConfirmation,
  ordersHoldApprove,
  ordersHoldReject,
  ordersModify,
  ordersReject,
  useOrdersRetrieve,
} from "@/lib/api/generated/endpoints/orders/orders";
import type { Fulfilment, OrderLine, StaffOrder } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney, formatQty } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { fromMilli, toMilli } from "@/lib/qty";

import { DocumentButton } from "@/components/billing/document-button";

import { ActionDialog } from "./action-dialog";
import { refreshOrders } from "./board";
import { OrdersNav } from "./orders-nav";

const ZERO = "0.000";

/** The order's tax invoices (one per shipment) and its Order Confirmation (Phase 5). */
function OrderDocuments({ order }: { order: StaffOrder }) {
  const t = useTranslations("orders.detail");
  const { can } = useAuth();
  if (!order.invoices.length && !order.has_confirmation) return null;
  return (
    <section className="space-y-2 rounded-xl border p-4" aria-labelledby="documents-heading">
      <h2 id="documents-heading" className="font-semibold">
        {t("documents")}
      </h2>
      {order.invoices.length ? (
        <ul className="divide-y text-sm">
          {order.invoices.map((invoice) => (
            <li key={invoice.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              {can("invoices.view") ? (
                <Link
                  href={`/manage/invoices/${invoice.id}`}
                  className="font-medium hover:underline"
                >
                  {invoice.number}
                </Link>
              ) : (
                <span className="font-medium">{invoice.number}</span>
              )}
              <span className="flex items-center gap-2">
                <MoneyText value={invoice.grand_total} />
                <StatusBadge status={invoice.payment_status} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {order.has_confirmation ? (
        <DocumentButton fetchLink={() => ordersConfirmation(order.id)}>
          {t("confirmation")}
        </DocumentButton>
      ) : null}
    </section>
  );
}

function useApply(orderId: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: getOrdersRetrieveQueryKey(orderId) });
    refreshOrders(client);
  };
}

/** The quantity still open on a line (ordered − cancelled), for editing before acceptance. */
function openQty(line: OrderLine): string {
  return fromMilli((toMilli(line.qty_ordered) ?? 0) - (toMilli(line.qty_cancelled) ?? 0));
}

function LineBreakdown({ line }: { line: OrderLine }) {
  const t = useTranslations("orders.detail.line");
  const parts = [
    ["reserved", line.qty_reserved],
    ["pending", line.qty_pending],
    ["waiting", line.qty_backordered],
    ["inShipments", line.qty_allocated],
    ["dispatched", line.qty_dispatched],
    ["delivered", line.qty_delivered],
    ["cancelled", line.qty_cancelled],
  ] as const;
  return (
    <p className="text-muted-foreground text-xs">
      {parts
        .filter(([, qty]) => qty !== ZERO)
        .map(([key, qty]) => t(key, { qty: formatQty(qty) }))
        .join(" · ")}
    </p>
  );
}

function ModifyDialog({ order }: { order: StaffOrder }) {
  const t = useTranslations("orders.detail");
  const apply = useApply(order.id);
  const [values, setValues] = useState<Record<string, string>>({});
  const changed = order.lines
    .map((line) => ({ line, value: values[line.id] }))
    .filter(({ line, value }) => value !== undefined && value !== openQty(line));
  return (
    <ActionDialog
      trigger={
        <Button variant="outline" className="min-h-10">
          {t("edit")}
        </Button>
      }
      title={t("editTitle")}
      description={t("editBody")}
      confirmLabel={t("save")}
      disabled={changed.length === 0}
      onSubmit={async () => {
        await ordersModify(order.id, {
          lines: changed.map(({ line, value }) => ({ line: line.id, quantity: value! })),
        });
        setValues({});
        apply();
      }}
    >
      <ul className="space-y-3">
        {order.lines
          .filter((line) => openQty(line) !== "0")
          .map((line) => (
            <li key={line.id} className="flex items-center justify-between gap-3">
              <Label htmlFor={`qty-${line.id}`} className="min-w-0 flex-1">
                {line.product_name}
              </Label>
              <Input
                id={`qty-${line.id}`}
                inputMode="decimal"
                className="min-h-10 w-24 text-right"
                value={values[line.id] ?? openQty(line)}
                onChange={(e) => setValues((v) => ({ ...v, [line.id]: e.target.value }))}
              />
            </li>
          ))}
      </ul>
    </ActionDialog>
  );
}

function OrderActions({ order }: { order: StaffOrder }) {
  const t = useTranslations("orders.detail");
  const { can } = useAuth();
  const { message } = useErrorText();
  const apply = useApply(order.id);
  const [acceptKey] = useState(newIdempotencyKey);
  const [accepting, setAccepting] = useState(false);
  const manage = can("orders.manage");
  const actions = [];
  if (order.status === "PLACED" && manage) {
    actions.push(
      <Button
        key="accept"
        className="min-h-10"
        disabled={accepting}
        onClick={async () => {
          setAccepting(true);
          try {
            await ordersAccept(order.id, idempotent(acceptKey));
            toast.success(t("acceptedToast", { number: order.number }));
            apply();
          } catch (error) {
            toast.error(message(error));
          } finally {
            setAccepting(false);
          }
        }}
      >
        {t("accept")}
      </Button>,
      <ModifyDialog key="edit" order={order} />,
      <ReasonDialog
        key="reject"
        trigger={
          <Button variant="outline" className="min-h-10">
            {t("reject")}
          </Button>
        }
        title={t("rejectTitle", { number: order.number })}
        description={t("rejectBody")}
        reasonLabel={t("reasonForShop")}
        confirmLabel={t("reject")}
        destructive
        onConfirm={async (reason) => {
          await ordersReject(order.id, { reason });
          apply();
        }}
      />,
    );
  }
  if (order.status === "ON_HOLD" && can("credit.manage")) {
    actions.push(
      <ConfirmDialog
        key="approve"
        trigger={<Button className="min-h-10">{t("approveHold")}</Button>}
        title={t("approveTitle", { number: order.number })}
        description={t("approveBody", { total: formatMoney(order.grand_total) })}
        confirmLabel={t("approveHold")}
        onConfirm={async () => {
          await ordersHoldApprove(order.id);
          apply();
        }}
      />,
      <ReasonDialog
        key="reject-hold"
        trigger={
          <Button variant="outline" className="min-h-10">
            {t("rejectHold")}
          </Button>
        }
        title={t("rejectTitle", { number: order.number })}
        reasonLabel={t("reasonForShop")}
        confirmLabel={t("reject")}
        destructive
        onConfirm={async (reason) => {
          await ordersHoldReject(order.id, { reason });
          apply();
        }}
      />,
    );
  }
  const cancellable = ["PLACED", "ON_HOLD", "ACCEPTED", "PACKED"].includes(order.status);
  if (cancellable && manage) {
    actions.push(
      <ReasonDialog
        key="cancel"
        trigger={
          <Button variant="ghost" className="text-destructive min-h-10">
            {t("cancel")}
          </Button>
        }
        title={t("cancelTitle", { number: order.number })}
        description={t("cancelBody")}
        reasonLabel={t("reasonForShop")}
        confirmLabel={t("cancel")}
        destructive
        onConfirm={async (reason) => {
          await ordersCancel(order.id, { reason });
          apply();
        }}
      />,
    );
  }
  return actions.length ? <div className="flex flex-wrap gap-2">{actions}</div> : null;
}

function PackDialog({ orderId, shipment }: { orderId: string; shipment: Fulfilment }) {
  const t = useTranslations("orders.shipment");
  const apply = useApply(orderId);
  const [values, setValues] = useState<Record<string, string>>({});
  return (
    <ActionDialog
      trigger={<Button className="min-h-10">{t("pack")}</Button>}
      title={t("packTitle", { number: shipment.number })}
      description={t("packBody")}
      confirmLabel={t("pack")}
      onSubmit={async () => {
        await fulfilmentsPack(shipment.id, {
          lines: Object.entries(values).map(([line, quantity]) => ({ line, quantity })),
        });
        apply();
      }}
    >
      <ul className="space-y-3">
        {shipment.lines.map((line) => (
          <li key={line.id} className="flex items-center justify-between gap-3">
            <Label htmlFor={`pack-${line.id}`} className="min-w-0 flex-1">
              {line.product_name}
              <span className="text-muted-foreground block text-xs">
                {t("ofQty", { qty: formatQty(line.quantity), unit: line.unit_code })}
              </span>
            </Label>
            <Input
              id={`pack-${line.id}`}
              inputMode="decimal"
              className="min-h-10 w-24 text-right"
              value={values[line.id] ?? fromMilli(toMilli(line.quantity) ?? 0)}
              onChange={(e) => setValues((v) => ({ ...v, [line.id]: e.target.value }))}
            />
          </li>
        ))}
      </ul>
    </ActionDialog>
  );
}

function DispatchDialog({ orderId, shipment }: { orderId: string; shipment: Fulfilment }) {
  const t = useTranslations("orders.shipment");
  const apply = useApply(orderId);
  const { feature } = useAuth();
  const ewaybills = feature("ewaybill");
  const [form, setForm] = useState({ vehicle_number: "", transporter_name: "", lr_number: "" });
  const [distance, setDistance] = useState(
    shipment.distance_km !== null ? String(shipment.distance_km) : "",
  );
  const field = (name: keyof typeof form, label: string) => (
    <div className="space-y-1.5">
      <Label htmlFor={`${name}-${shipment.id}`}>{label}</Label>
      <Input
        id={`${name}-${shipment.id}`}
        value={form[name]}
        onChange={(e) => setForm((f) => ({ ...f, [name]: e.target.value }))}
        className="min-h-10"
      />
    </div>
  );
  return (
    <ActionDialog
      trigger={<Button className="min-h-10">{t("dispatch")}</Button>}
      title={t("dispatchTitle", { number: shipment.number })}
      description={t("dispatchBody")}
      confirmLabel={t("dispatch")}
      onSubmit={async () => {
        const km = distance.trim();
        await fulfilmentsDispatch(shipment.id, {
          ...form,
          // For the e-way bill (Phase 7): sent as typed; the server checks it.
          ...(ewaybills && km
            ? { distance_km: /^\d+$/.test(km) ? Number(km) : (km as never) }
            : {}),
        });
        apply();
      }}
    >
      {field("vehicle_number", t("vehicle"))}
      {field("transporter_name", t("transporter"))}
      {field("lr_number", t("lr"))}
      {ewaybills ? (
        <div className="space-y-1.5">
          <Label htmlFor={`distance-${shipment.id}`}>{t("distance")}</Label>
          <Input
            id={`distance-${shipment.id}`}
            inputMode="numeric"
            value={distance}
            onChange={(e) => setDistance(e.target.value)}
            className="min-h-10"
          />
          <p className="text-muted-foreground text-xs">{t("distanceHint")}</p>
        </div>
      ) : null}
    </ActionDialog>
  );
}

function CancelShipmentDialog({ orderId, shipment }: { orderId: string; shipment: Fulfilment }) {
  const t = useTranslations("orders.shipment");
  const apply = useApply(orderId);
  const [toBackorder, setToBackorder] = useState(true);
  const [reason, setReason] = useState("");
  return (
    <ActionDialog
      trigger={
        <Button variant="ghost" className="text-destructive min-h-10">
          {t("cancel")}
        </Button>
      }
      title={t("cancelTitle", { number: shipment.number })}
      confirmLabel={t("cancel")}
      destructive
      disabled={!reason.trim()}
      onSubmit={async () => {
        await fulfilmentsCancel(shipment.id, { to_backorder: toBackorder, reason: reason.trim() });
        apply();
      }}
    >
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("whatHappens")}</legend>
        {[true, false].map((value) => (
          <label key={String(value)} className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="radio"
              name={`after-${shipment.id}`}
              checked={toBackorder === value}
              onChange={() => setToBackorder(value)}
              className="size-4"
            />
            {value ? t("backToWaiting") : t("cancelItems")}
          </label>
        ))}
      </fieldset>
      <div className="space-y-1.5">
        <Label htmlFor={`reason-${shipment.id}`}>{t("reason")}</Label>
        <Input
          id={`reason-${shipment.id}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="min-h-10"
        />
      </div>
    </ActionDialog>
  );
}

function ShipmentCard({ order, shipment }: { order: StaffOrder; shipment: Fulfilment }) {
  const t = useTranslations("orders.shipment");
  const { can } = useAuth();
  const apply = useApply(order.id);
  const fulfil = can("orders.fulfil");
  const open = shipment.status === "ALLOCATED" || shipment.status === "PACKED";
  return (
    <li className="space-y-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium">
          <Truck aria-hidden className="size-4" />
          {shipment.number}
          {shipment.kind === "BACKORDER" ? (
            <span className="text-muted-foreground text-xs font-normal">{t("backorder")}</span>
          ) : null}
        </span>
        <StatusBadge status={shipment.status} labels="shipmentStatus" />
      </div>
      <ul className="space-y-1 text-sm">
        {shipment.lines.map((line) => (
          <li key={line.id} className="flex flex-wrap justify-between gap-x-3">
            <span>
              {line.product_name}
              {line.cancelled_by_retailer_at ? (
                <span className="text-muted-foreground"> · {t("declined")}</span>
              ) : null}
            </span>
            <span className="tabular-nums">
              {line.qty_packed !== null && line.qty_packed !== line.quantity
                ? t("packedOf", {
                    packed: formatQty(line.qty_packed),
                    qty: formatQty(line.quantity),
                  })
                : formatQty(line.quantity)}{" "}
              {line.unit_code}
            </span>
            {line.price_increased ? (
              <span className="text-warning-strong w-full text-xs">
                {t("priceUp", {
                  before: formatMoney(line.ordered_price),
                  now: formatMoney(line.unit_price),
                })}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {shipment.dispatched_at ? (
        <p className="text-muted-foreground text-xs">
          {t("dispatchedOn")} <DateText value={shipment.dispatched_at} withTime />
          {[shipment.vehicle_number, shipment.transporter_name, shipment.lr_number]
            .filter(Boolean)
            .map((part) => ` · ${part}`)
            .join("")}
          {shipment.distance_km !== null ? ` · ${t("km", { km: shipment.distance_km })}` : ""}
        </p>
      ) : null}
      {shipment.cancelled_reason ? (
        <p className="text-muted-foreground text-xs">{shipment.cancelled_reason}</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {fulfil && shipment.status === "ALLOCATED" ? (
          <PackDialog orderId={order.id} shipment={shipment} />
        ) : null}
        {fulfil && shipment.status === "PACKED" ? (
          <DispatchDialog orderId={order.id} shipment={shipment} />
        ) : null}
        {fulfil && shipment.status === "DISPATCHED" ? (
          <ConfirmDialog
            trigger={<Button className="min-h-10">{t("deliver")}</Button>}
            title={t("deliverTitle", { number: shipment.number })}
            confirmLabel={t("deliver")}
            onConfirm={async () => {
              await fulfilmentsDeliver(shipment.id);
              apply();
            }}
          />
        ) : null}
        {open && can("orders.manage") ? (
          <CancelShipmentDialog orderId={order.id} shipment={shipment} />
        ) : null}
      </div>
    </li>
  );
}

export function StaffOrderPage({ orderId }: { orderId: string }) {
  const t = useTranslations("orders.detail");
  const { can } = useAuth();
  const query = useOrdersRetrieve(orderId);
  const apply = useApply(orderId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return (
      <EmptyState
        title={t("goneTitle")}
        action={
          <Button asChild className="min-h-11">
            <Link href="/manage/orders">{t("back")}</Link>
          </Button>
        }
      />
    );
  }
  const order = query.data.data;
  const address = (order.shipping_address ?? {}) as Record<string, string>;
  const waiting = ["ACCEPTED", "PACKED", "DISPATCHED", "PARTLY_DELIVERED"].includes(order.status);
  return (
    <>
      <OrdersNav />
      <div className="space-y-6">
        <Button asChild variant="ghost" className="-ml-3 min-h-10">
          <Link href="/manage/orders">
            <ArrowLeft aria-hidden />
            {t("back")}
          </Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold">{order.number}</h1>
            <OrderStatus status={order.status} itemsToFollow={order.items_to_follow} />
            <p className="text-muted-foreground text-sm">
              <Link href={`/manage/retailers/${order.retailer}`} className="hover:underline">
                {order.retailer_name}
              </Link>
              {" · "}
              <DateText value={order.placed_at} withTime />
              {order.placed_by_label ? ` · ${t("placedBy", { name: order.placed_by_label })}` : ""}
            </p>
          </div>
          <OrderActions order={order} />
        </div>
        {order.status === "ON_HOLD" ? (
          <p className="bg-warning/15 rounded-xl p-3 text-sm">
            {t(order.hold_reason === "OVERDUE" ? "onHoldOverdue" : "onHold")}
          </p>
        ) : null}
        {order.credit_approved_value ? (
          <p className="bg-info/10 rounded-xl p-3 text-sm">
            {t("approvedOverLimit", { amount: formatMoney(order.credit_approved_value) })}
          </p>
        ) : null}
        {order.rejection_reason ? (
          <p className="bg-destructive/10 rounded-xl p-3 text-sm">
            {t("rejectedBecause", { reason: order.rejection_reason })}
          </p>
        ) : null}
        {order.cancellation_reason ? (
          <p className="bg-muted rounded-xl p-3 text-sm">
            {t("cancelledBecause", { reason: order.cancellation_reason })}
          </p>
        ) : null}
        <div className="grid gap-6 xl:grid-cols-[1fr_24rem] xl:items-start">
          <div className="space-y-6">
            <section className="space-y-2" aria-labelledby="lines-heading">
              <h2 id="lines-heading" className="font-semibold">
                {t("items")}
              </h2>
              <ul className="divide-y rounded-xl border">
                {order.lines.map((line) => (
                  <li key={line.id} className="space-y-1 p-3">
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block font-medium">{line.product_name}</span>
                        <span className="text-muted-foreground text-xs">
                          {line.product_code} · {formatQty(line.qty_ordered)} {line.unit_code} ×{" "}
                          <MoneyText value={line.unit_price} />
                        </span>
                      </span>
                      <MoneyText value={line.line_total} className="font-medium" />
                    </div>
                    <LineBreakdown line={line} />
                    {line.on_order ? (
                      <p className="text-xs">
                        {t("onOrder", {
                          qty: formatQty(line.on_order.quantity),
                          unit: line.unit_code,
                        })}
                        {line.on_order.expected_date ? (
                          <>
                            {" "}
                            {t("expectedOn")} <DateText value={line.on_order.expected_date} />
                          </>
                        ) : null}
                        {line.on_order.late ? ` · ${t("late")}` : ""}
                      </p>
                    ) : null}
                    {waiting && line.qty_backordered !== ZERO && can("orders.manage") ? (
                      <ConfirmDialog
                        trigger={
                          <Button variant="outline" size="sm" className="min-h-10">
                            {t("cancelWaiting")}
                          </Button>
                        }
                        title={t("cancelWaitingTitle", { name: line.product_name })}
                        description={t("cancelWaitingBody", {
                          qty: formatQty(line.qty_backordered),
                        })}
                        confirmLabel={t("cancelWaiting")}
                        destructive
                        onConfirm={async () => {
                          await orderLinesCancelBackorder(line.id);
                          apply();
                        }}
                      />
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
            {order.fulfilments.length ? (
              <section className="space-y-2" aria-labelledby="shipments-heading">
                <h2 id="shipments-heading" className="font-semibold">
                  {t("shipments")}
                </h2>
                <ul className="space-y-3">
                  {order.fulfilments.map((shipment) => (
                    <ShipmentCard key={shipment.id} order={order} shipment={shipment} />
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
          <aside className="space-y-6">
            <section className="space-y-2 rounded-xl border p-4" aria-labelledby="totals-heading">
              <h2 id="totals-heading" className="font-semibold">
                {t("totals")}
              </h2>
              <dl className="space-y-1 text-sm">
                {[
                  ["taxable", order.taxable_total],
                  ["gst", order.tax_total],
                  ["roundOff", order.round_off],
                ].map(([key, value]) => (
                  <div key={key} className="flex justify-between">
                    <dt>{t(key as "taxable")}</dt>
                    <dd>
                      <MoneyText value={value!} />
                    </dd>
                  </div>
                ))}
                <div className="flex justify-between text-base font-semibold">
                  <dt>{t("total")}</dt>
                  <dd>
                    <MoneyText value={order.grand_total} />
                  </dd>
                </div>
              </dl>
              {address.line1 ? (
                <p className="pt-2 text-sm">
                  <span className="text-muted-foreground block">{t("deliverTo")}</span>
                  {[address.line1, address.line2, address.city, address.pincode]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              ) : null}
              {order.retailer_note ? (
                <p className="text-sm">
                  <span className="text-muted-foreground block">{t("note")}</span>
                  {order.retailer_note}
                </p>
              ) : null}
            </section>
            <OrderDocuments order={order} />
            <section className="space-y-3" aria-labelledby="timeline-heading">
              <h2 id="timeline-heading" className="font-semibold">
                {t("timeline")}
              </h2>
              <OrderTimeline entries={order.history} />
            </section>
          </aside>
        </div>
      </div>
    </>
  );
}
