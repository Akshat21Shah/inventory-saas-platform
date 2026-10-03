import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { router, Stack, useLocalSearchParams } from "expo-router";
import { useState, type ReactNode } from "react";
import { Alert, StyleSheet, View } from "react-native";

import { confirm } from "@/components/shared/confirm";
import { DocumentButton } from "@/components/shared/document-button";
import { OrderTimeline } from "@/components/shared/order-timeline";
import { EmptyState, ListSkeleton } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { DateText, MoneyText } from "@/components/shared/values";
import { OrderStatus } from "@/components/shop/order-row";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  getShopCartRetrieveQueryKey,
  getShopOrderQueryKey,
  shopFulfilmentLineCancelRepriced,
  shopFulfilmentReceived,
  shopOrderCancel,
  shopOrderLineCancelBackorder,
  shopOrderRepeat,
  shopOrdersConfirmation,
  shopInvoicesPdf,
  useShopOrder,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { OrderLine, ShopFulfilment, ShopOrder } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { formatMoney, formatQty } from "@/lib/shared/format";
import { fromMilli, toMilli } from "@/lib/shared/qty";
import { space, useTheme } from "@/lib/theme/theme";

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

/** Run a change and show the server's words if it is refused. */
function useAct() {
  const { message } = useErrorText();
  return async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (error) {
      Alert.alert(message(error));
    }
  };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={styles.section}>
      <Text weight="semibold">{title}</Text>
      {children}
    </View>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "success" | "warning" | "danger" | "muted";
  children: ReactNode;
}) {
  const { colors, radius } = useTheme();
  const background = {
    success: colors.success + "1f",
    warning: colors.warning + "26",
    danger: colors.destructive + "1a",
    muted: colors.muted,
  }[tone];
  return (
    <View
      accessibilityRole={tone === "danger" ? "alert" : "text"}
      style={[styles.banner, { backgroundColor: background, borderRadius: radius }]}
    >
      {children}
    </View>
  );
}

function LineState({ line }: { line: OrderLine }) {
  const t = useTranslations("shop.orders.line");
  const parts: string[] = [];
  const q = (v: string) => formatQty(v);
  if (line.qty_delivered !== "0.000") parts.push(t("delivered", { qty: q(line.qty_delivered) }));
  const onTheWay = (toMilli(line.qty_dispatched) ?? 0) - (toMilli(line.qty_delivered) ?? 0);
  if (onTheWay > 0) parts.push(t("onTheWay", { qty: formatQty(fromMilli(onTheWay)) }));
  if (line.ready_qty !== "0.000" && line.ready_qty !== "0")
    parts.push(t("ready", { qty: q(line.ready_qty) }));
  if (line.qty_pending !== "0.000") parts.push(t("pending", { qty: q(line.qty_pending) }));
  if (line.qty_backordered !== "0.000") parts.push(t("waiting", { qty: q(line.qty_backordered) }));
  if (line.qty_cancelled !== "0.000") parts.push(t("cancelled", { qty: q(line.qty_cancelled) }));
  return (
    <Text tone="muted" size="xs">
      {parts.join(" · ")}
    </Text>
  );
}

function Lines({ order }: { order: ShopOrder }) {
  const t = useTranslations("shop.orders");
  const tf = useTranslations("shop.free");
  const common = useTranslations("common");
  const refresh = useRefresh(order.id);
  const act = useAct();
  const waitingAllowed = ["ACCEPTED", "PACKED", "DISPATCHED", "PARTLY_DELIVERED"].includes(
    order.status,
  );
  return (
    <Section title={t("itemsTitle")}>
      <Card>
        {order.lines.map((line, index) => (
          <View key={line.id} style={[styles.line, index > 0 && styles.divider]}>
            <View style={styles.between}>
              <View style={styles.flex}>
                <Text weight="medium">{line.product_name}</Text>
                {line.free_of_line ? (
                  <Text tone="success" size="xs" weight="medium">
                    {tf("badge")}
                    {line.scheme_name ? ` · ${tf("under", { scheme: line.scheme_name })}` : ""}
                  </Text>
                ) : null}
                <Text tone="muted" size="xs">
                  {formatQty(line.qty_ordered)} {line.unit_code} ×{" "}
                  <MoneyText value={line.unit_price} tone="muted" size="xs" />
                </Text>
              </View>
              <MoneyText value={line.line_total} weight="medium" />
            </View>
            <LineState line={line} />
            {waitingAllowed && line.qty_backordered !== "0.000" ? (
              <Button
                variant="outline"
                label={t("cancelWaiting")}
                onPress={() =>
                  confirm({
                    title: t("cancelWaitingTitle", { name: line.product_name }),
                    body: t("cancelWaitingBody", { qty: formatQty(line.qty_backordered) }),
                    confirmLabel: t("cancelWaiting"),
                    cancelLabel: common("cancel"),
                    destructive: true,
                    onConfirm: () =>
                      act(async () => refresh(await shopOrderLineCancelBackorder(line.id))),
                  })
                }
              />
            ) : null}
          </View>
        ))}
      </Card>
    </Section>
  );
}

function Shipment({ order, shipment }: { order: ShopOrder; shipment: ShopFulfilment }) {
  const t = useTranslations("shop.orders");
  const common = useTranslations("common");
  const refresh = useRefresh(order.id);
  const act = useAct();
  const { colors, radius } = useTheme();
  const onItsWay = shipment.status === "DISPATCHED";
  return (
    <Card>
      <View style={styles.between}>
        <View style={styles.inline}>
          <Feather name="truck" size={16} color={colors.foreground} />
          <Text weight="medium">{shipment.number}</Text>
        </View>
        <StatusBadge status={shipment.status} labels="shipmentStatus" />
      </View>
      {shipment.dispatched_at ? (
        <Text tone="muted" size="xs">
          {t("sentOn")} <DateText value={shipment.dispatched_at} withTime tone="muted" size="xs" />
          {shipment.vehicle_number ? ` · ${shipment.vehicle_number}` : ""}
        </Text>
      ) : null}
      {onItsWay && shipment.delivery_code ? (
        <View style={[styles.code, { backgroundColor: colors.info + "1a", borderRadius: radius }]}>
          <Text size="sm">{t("codeIntro")}</Text>
          <Text
            size="2xl"
            weight="bold"
            style={styles.codeText}
            accessibilityLabel={t("codeLabel", {
              code: shipment.delivery_code.split("").join(" "),
            })}
          >
            {shipment.delivery_code}
          </Text>
        </View>
      ) : null}
      {onItsWay && shipment.can_confirm ? (
        <Button
          label={t("received")}
          icon={<Feather name="package" size={16} color={colors.primaryForeground} />}
          onPress={() =>
            confirm({
              title: t("receivedTitle", { number: shipment.number }),
              body: t("receivedBody"),
              confirmLabel: t("received"),
              cancelLabel: common("cancel"),
              onConfirm: () => act(async () => refresh(await shopFulfilmentReceived(shipment.id))),
            })
          }
        />
      ) : null}
      {shipment.lines.map((line) => (
        <View key={line.id} style={styles.gapXs}>
          <Text size="sm" style={line.cancelled_by_retailer_at ? styles.strike : undefined}>
            {line.product_name}: {formatQty(line.qty_packed ?? line.quantity)} {line.unit_code}
          </Text>
          {line.price_increased && !line.cancelled_by_retailer_at ? (
            <View
              style={[
                styles.banner,
                { backgroundColor: colors.warning + "26", borderRadius: radius },
              ]}
            >
              <Text size="xs">
                {t("priceUp", {
                  before: formatMoney(line.ordered_price),
                  now: formatMoney(line.unit_price),
                })}
              </Text>
              {shipment.status === "ALLOCATED" ? (
                <Button
                  variant="outline"
                  label={t("decline")}
                  onPress={() =>
                    confirm({
                      title: t("declineTitle", { name: line.product_name }),
                      body: t("declineBody"),
                      confirmLabel: t("decline"),
                      cancelLabel: common("cancel"),
                      destructive: true,
                      onConfirm: () =>
                        act(async () => refresh(await shopFulfilmentLineCancelRepriced(line.id))),
                    })
                  }
                />
              ) : null}
            </View>
          ) : null}
        </View>
      ))}
    </Card>
  );
}

function Documents({ order }: { order: ShopOrder }) {
  const t = useTranslations("shop.orders");
  if (!order.invoices.length && !order.has_confirmation) return null;
  return (
    <Section title={t("documents")}>
      {order.invoices.map((bill) => (
        // The bill's own screen comes with 11b.7; until then it opens the bill itself.
        <DocumentButton
          key={bill.id}
          label={`${bill.number} · ${formatMoney(bill.grand_total)}`}
          fetchLink={() => shopInvoicesPdf(bill.id)}
        />
      ))}
      {order.has_confirmation ? (
        <DocumentButton
          label={t("confirmation")}
          fetchLink={() => shopOrdersConfirmation(order.id)}
        />
      ) : null}
    </Section>
  );
}

export default function OrderScreen() {
  const { id, placed } = useLocalSearchParams<{ id: string; placed?: string }>();
  const t = useTranslations("shop.orders");
  const common = useTranslations("common");
  const client = useQueryClient();
  const { message } = useErrorText();
  const { colors } = useTheme();
  const query = useShopOrder(id);
  const refresh = useRefresh(id);
  const act = useAct();
  const [repeating, setRepeating] = useState(false);
  const order = query.data?.data;

  if (query.isLoading) {
    return (
      <Screen edges={["bottom"]}>
        <ListSkeleton />
      </Screen>
    );
  }
  if (query.error || !order) {
    return (
      <Screen edges={["bottom"]}>
        <EmptyState
          icon="clipboard"
          title={t("goneTitle")}
          action={{ label: t("title"), onPress: () => router.replace("/shop/orders") }}
        />
      </Screen>
    );
  }
  const cancellable = order.status === "PLACED" || order.status === "ON_HOLD";
  const repeat = async () => {
    setRepeating(true);
    try {
      const response = await shopOrderRepeat(order.id);
      client.setQueryData(getShopCartRetrieveQueryKey(), { ...response, data: response.data.cart });
      if (response.data.skipped.length)
        Alert.alert(t("skipped", { count: response.data.skipped.length }));
      router.push("/shop/cart");
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setRepeating(false);
    }
  };
  return (
    <>
      <Stack.Screen options={{ title: order.number }} />
      <Screen
        edges={["bottom"]}
        refreshing={query.isRefetching}
        onRefresh={() => void query.refetch()}
      >
        {placed === "1" ? (
          <Banner tone="success">
            <Feather name="check-circle" size={20} color={colors.successStrong} />
            <View style={styles.flex}>
              <Text weight="semibold">{t("placedTitle")}</Text>
              <Text size="sm">{t("placedBody")}</Text>
            </View>
          </Banner>
        ) : null}
        <View style={styles.gapXs}>
          <Text size="2xl" weight="bold">
            {order.number}
          </Text>
          <OrderStatus status={order.status} itemsToFollow={order.items_to_follow} />
          <Text tone="muted" size="sm">
            <DateText value={order.placed_at} withTime tone="muted" size="sm" />
            {order.placed_by_label ? ` · ${t("placedBy", { name: order.placed_by_label })}` : ""}
          </Text>
        </View>
        {order.status === "ON_HOLD" ? (
          <Banner tone="warning">
            <Text size="sm" style={styles.flex}>
              {t(order.hold_reason === "OVERDUE" ? "onHoldOverdue" : "onHold")}
            </Text>
          </Banner>
        ) : null}
        {order.rejection_reason ? (
          <Banner tone="danger">
            <Text size="sm" style={styles.flex}>
              {t("rejectedBecause", { reason: order.rejection_reason })}
            </Text>
          </Banner>
        ) : null}
        {order.status === "CANCELLED" && order.cancellation_reason ? (
          <Banner tone="muted">
            <Text size="sm" style={styles.flex}>
              {t("cancelledBecause", { reason: order.cancellation_reason })}
            </Text>
          </Banner>
        ) : null}
        <Lines order={order} />
        {order.fulfilments.length ? (
          <Section title={t("shipmentsTitle")}>
            {order.fulfilments.map((shipment) => (
              <Shipment key={shipment.id} order={order} shipment={shipment} />
            ))}
          </Section>
        ) : null}
        <Card>
          <Documents order={order} />
          <View style={styles.between}>
            <Text size="sm">{t("gst")}</Text>
            <MoneyText value={order.tax_total} size="sm" />
          </View>
          <View style={styles.between}>
            <Text weight="semibold">{t("total")}</Text>
            <MoneyText value={order.grand_total} weight="semibold" />
          </View>
          {order.retailer_note ? (
            <Text size="sm">
              <Text tone="muted" size="sm">
                {t("note")}:{" "}
              </Text>
              {order.retailer_note}
            </Text>
          ) : null}
          <Button
            variant="outline"
            label={t("orderAgain")}
            busy={repeating}
            icon={<Feather name="rotate-ccw" size={16} color={colors.foreground} />}
            onPress={() => void repeat()}
          />
          {cancellable ? (
            <Button
              variant="ghost"
              label={t("cancel")}
              onPress={() =>
                confirm({
                  title: t("cancelTitle", { number: order.number }),
                  body: t("cancelBody"),
                  confirmLabel: t("cancel"),
                  cancelLabel: common("cancel"),
                  destructive: true,
                  onConfirm: () =>
                    act(async () => refresh(await shopOrderCancel(order.id, { reason: "" }))),
                })
              }
            />
          ) : null}
        </Card>
        <Section title={t("timelineTitle")}>
          <OrderTimeline entries={order.history} />
        </Section>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  section: { gap: space[2] },
  gapXs: { gap: space[1] },
  inline: { flexDirection: "row", alignItems: "center", gap: space[2] },
  between: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: space[3],
  },
  banner: {
    flexDirection: "row",
    gap: space[2],
    padding: space[3],
    alignItems: "flex-start",
    flexWrap: "wrap",
  },
  line: { gap: space[1], paddingVertical: space[2] },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: "#e5e5e5" },
  code: { padding: space[3], gap: space[1] },
  codeText: { letterSpacing: 8 },
  strike: { textDecorationLine: "line-through" },
});
