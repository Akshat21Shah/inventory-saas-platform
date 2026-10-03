/**
 * Cart and one-screen checkout, the app's twin of `web/components/shop/cart.tsx` (ADR-044): what
 * can be sent now and what later, problems to fix in the server's words, the delivery address and
 * instructions, the server's totals, and "Place order" with safe retries (ADR-061 item 10).
 */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { Link, router } from "expo-router";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Alert, Pressable, StyleSheet, TextInput, View } from "react-native";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { MoneyText } from "@/components/shared/values";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
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
import { useAuth } from "@/lib/auth/auth-provider";
import { useCart } from "@/lib/cart/cart-state";
import { attemptFor, finishAttempt, pendingAttempt } from "@/lib/cart/checkout";
import { useTranslations } from "@/lib/i18n/translations";
import { ApiError, NETWORK_ERROR } from "@/lib/shared/errors";
import { formatMoney, formatQty } from "@/lib/shared/format";
import { idempotent } from "@/lib/shared/idempotency";
import { space, text, useTheme } from "@/lib/theme/theme";

import { OnHoldNotice, Thumb } from "./product";
import { QuantityStepper } from "./quantity-stepper";

/** A problem from the server in plain words (codes from apps/orders/quote.py). */
export function ProblemText({ problem, unit }: { problem: Problem; unit?: string }) {
  const t = useTranslations("shop.cart.problems");
  const d = problem.details as Record<string, string | undefined>;
  const qty = (value?: string) => (value ? formatQty(value) : "");
  switch (problem.code) {
    case "QTY_BELOW_MINIMUM":
      return t("QTY_BELOW_MINIMUM", { qty: qty(d.minimum), unit: unit ?? "" });
    case "QTY_NOT_MULTIPLE":
      return t("QTY_NOT_MULTIPLE", { qty: qty(d.step) });
    case "NOT_ENOUGH_STOCK":
    case "PARTLY_AVAILABLE":
      return t(problem.code, { qty: qty(d.available), unit: unit ?? "" });
    case "FREE_GOODS_REDUCED":
      return t("FREE_GOODS_REDUCED", { qty: qty(d.available), earned: qty(d.earned) });
    case "MIN_ORDER_VALUE":
      return t(d.basis === "INCL_GST" ? "MIN_ORDER_VALUE" : "MIN_ORDER_VALUE_EXCL", {
        amount: d.minimum ? formatMoney(d.minimum) : "",
      });
    case "CREDIT_LIMIT_EXCEEDED":
      return t("CREDIT_LIMIT_EXCEEDED", { amount: formatMoney(d.available ?? "0") });
    default:
      return t.has(problem.code) ? t(problem.code) : t("OTHER");
  }
}

function Notice({ tone, children }: { tone: "warning" | "info" | "danger"; children: ReactNode }) {
  const { colors, radius } = useTheme();
  const background = {
    warning: colors.warning + "26",
    info: colors.info + "1a",
    danger: colors.destructive + "1a",
  }[tone];
  const icon = tone === "info" ? "info" : tone === "danger" ? "alert-octagon" : "alert-triangle";
  return (
    <View
      accessibilityRole={tone === "danger" ? "alert" : "text"}
      style={[styles.notice, { backgroundColor: background, borderRadius: radius }]}
    >
      <Feather name={icon} size={16} color={colors.foreground} />
      <Text size="sm" style={styles.flex}>
        {children}
      </Text>
    </View>
  );
}

const lineKey = (line: Pick<QuoteLine, "product_id" | "is_free">) =>
  `${line.product_id}${line.is_free ? ":free" : ""}`;

function FreeLineLabel({ scheme }: { scheme: string }) {
  const t = useTranslations("shop.free");
  const { colors } = useTheme();
  return (
    <View style={styles.inline}>
      <View style={[styles.pill, { backgroundColor: colors.success + "1f" }]}>
        <Text size="xs" weight="medium" tone="success">
          {t("badge")}
        </Text>
      </View>
      {scheme ? (
        <Text tone="muted" size="xs">
          {t("under", { scheme })}
        </Text>
      ) : null}
    </View>
  );
}

function CartLine({ line }: { line: QuoteLine }) {
  const t = useTranslations("shop.cart");
  const tf = useTranslations("shop.free");
  const { colors } = useTheme();
  const product = line.product;
  if (!product) {
    return (
      <Card>
        <Text size="sm">{t("gone")}</Text>
      </Card>
    );
  }
  const later = line.later_qty !== "0.000";
  return (
    <Card>
      <View style={styles.row}>
        <Thumb url={product.thumbnail_url} size={64} />
        <View style={styles.flex}>
          <Link href={`/shop/products/${product.id}`}>
            <Text weight="medium">{product.name}</Text>
          </Link>
          {line.is_free ? <FreeLineLabel scheme={line.scheme?.name ?? ""} /> : null}
          {line.unit_price && !line.is_free ? (
            <Text tone="muted" size="xs">
              <MoneyText value={line.unit_price} tone="muted" size="xs" /> {t("each")}
              {line.discount_total && line.discount_total !== "0.00" ? (
                <Text tone="success" size="xs">
                  {" · "}
                  {t("saving", { amount: formatMoney(line.discount_total) })}
                </Text>
              ) : null}
            </Text>
          ) : null}
          {later ? (
            <Text size="xs" style={{ color: colors.infoStrong }}>
              {line.ready_qty !== "0.000"
                ? t("splitNowLater", {
                    now: formatQty(line.ready_qty),
                    later: formatQty(line.later_qty),
                    unit: product.unit.name,
                  })
                : t("allLater")}
            </Text>
          ) : null}
        </View>
        {line.is_free ? (
          <Text tone="success" weight="semibold">
            {t("freeQty", { qty: formatQty(line.quantity) })}
          </Text>
        ) : line.line_total ? (
          <MoneyText value={line.line_total} weight="semibold" />
        ) : null}
      </View>
      {line.is_free ? null : (
        <View style={styles.lineFoot}>
          {line.offer ? (
            <Text tone="success" size="xs" weight="medium" style={styles.flex}>
              {tf("addMore", {
                qty: formatQty(line.offer.add_qty),
                free: formatQty(line.offer.free_qty),
              })}
            </Text>
          ) : (
            <View style={styles.flex} />
          )}
          <QuantityStepper product={product} />
        </View>
      )}
      {line.problems.map((problem) => (
        <Text key={problem.code} size="sm" tone={problem.blocking ? "danger" : "warning"}>
          <ProblemText problem={problem} unit={product.unit.name} />
        </Text>
      ))}
    </Card>
  );
}

function Totals({ quote }: { quote: Quote }) {
  const t = useTranslations("shop.cart");
  const x = quote.totals;
  const row = (label: string, value: string, strong = false) => (
    <View style={styles.between} key={label}>
      <Text size={strong ? "base" : "sm"} weight={strong ? "semibold" : "normal"}>
        {label}
      </Text>
      <MoneyText
        value={value}
        size={strong ? "base" : "sm"}
        weight={strong ? "semibold" : "normal"}
      />
    </View>
  );
  return (
    <View style={styles.gapSm}>
      {row(t("itemsTotal"), x.gross)}
      {x.discount !== "0.00" ? row(t("discount"), `-${x.discount}`) : null}
      {row(t("gst"), x.tax)}
      {x.round_off !== "0.00" ? row(t("roundOff"), x.round_off) : null}
      {row(t("total"), x.grand_total, true)}
      <Text tone="muted" size="xs">
        {t("estimate")}
      </Text>
    </View>
  );
}

type Stage =
  | { kind: "idle" }
  | { kind: "placing" }
  | { kind: "checking" }
  | { kind: "unknown" }
  | { kind: "offline" };

export function CartScreen() {
  const t = useTranslations("shop.cart");
  const common = useTranslations("common");
  const client = useQueryClient();
  const { me } = useAuth();
  const { message } = useErrorText();
  const { colors, radius } = useTheme();
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

  const placed = async (orderId: string) => {
    await finishAttempt(owner);
    void client.invalidateQueries({
      predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/v1/shop/"),
    });
    router.push({ pathname: "/shop/orders/[id]", params: { id: orderId, placed: "1" } });
  };

  // Opened again after the app was closed mid-checkout: did that order go through?
  useEffect(() => {
    if (checkedLeftover.current || !me) return;
    checkedLeftover.current = true;
    void pendingAttempt(owner).then((leftover) => {
      if (!leftover) return;
      shopCheckoutAttempt(leftover.key)
        .then(({ data }) => {
          if (data.status === "placed" && data.order) void placed(data.order);
        })
        .catch(() => undefined);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the person is known
  }, [me]);

  if (query.isLoading) {
    return (
      <Screen>
        <ListSkeleton />
      </Screen>
    );
  }
  if (query.error || !quote) {
    return (
      <Screen>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }
  if (quote.lines.length === 0) {
    return (
      <Screen>
        <EmptyState
          icon="shopping-cart"
          title={t("emptyTitle")}
          body={t("emptyBody")}
          action={{ label: t("browse"), onPress: () => router.push("/shop/catalog") }}
        />
      </Screen>
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
    const attempt = await attemptFor(owner, `${version}|${quote.address_id ?? ""}|${note.trim()}`);
    try {
      if (stage.kind === "unknown" || stage.kind === "offline") {
        setStage({ kind: "checking" }); // ask first: the last try may have gone through
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
      await placed(response.data.id);
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

  const label =
    stage.kind === "placing"
      ? t("placing")
      : stage.kind === "checking"
        ? t("checking")
        : stage.kind === "unknown" || stage.kind === "offline"
          ? t("tryAgain")
          : t("place", { total: formatMoney(quote.totals.grand_total) });
  const list = addresses.data?.data ?? [];

  return (
    <Screen
      refreshing={query.isRefetching}
      onRefresh={() => void query.refetch()}
      footer={
        <Button
          label={label}
          busy={busy}
          disabled={!quote.can_place || pending || busy}
          onPress={() => void submit()}
        />
      }
    >
      <Text size="2xl" weight="bold">
        {t("title")}
      </Text>
      <OnHoldNotice />
      {ready.length ? (
        <View style={styles.gap}>
          <Text weight="semibold">
            {t("readyTitle", { count: ready.filter((l) => !l.is_free).length || ready.length })}
          </Text>
          {ready.map((line) => (
            <CartLine key={lineKey(line)} line={line} />
          ))}
        </View>
      ) : null}
      {later.length ? (
        <View style={styles.gap}>
          <Text weight="semibold">
            {quote.backorders_enabled ? t("laterTitle") : t("shortTitle")}
          </Text>
          <Text tone="muted" size="sm">
            {quote.backorders_enabled ? t("laterBody") : t("shortBody")}
          </Text>
          {later.map((line) => (
            <CartLine key={lineKey(line)} line={line} />
          ))}
          {canReduce ? (
            <Button
              variant="outline"
              label={t("reduce")}
              onPress={async () => {
                const response = await shopCartReduceToAvailable();
                client.setQueryData(getShopCartRetrieveQueryKey(), response);
                void query.refetch();
              }}
            />
          ) : null}
        </View>
      ) : null}
      <Card>
        <Text weight="semibold">{t("checkoutTitle")}</Text>
        {list.length > 1 ? (
          <View
            style={styles.gapSm}
            accessibilityRole="radiogroup"
            accessibilityLabel={t("deliverTo")}
          >
            <Text size="sm" weight="medium">
              {t("deliverTo")}
            </Text>
            {list.map((a) => {
              const on = (quote.address_id ?? "") === a.id;
              return (
                <Pressable
                  key={a.id}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: on }}
                  onPress={() => setAddress(a.id)}
                  style={[
                    styles.option,
                    { borderColor: on ? colors.primary : colors.border, borderRadius: radius },
                  ]}
                >
                  <Feather
                    name={on ? "check-circle" : "circle"}
                    size={18}
                    color={on ? colors.primary : colors.mutedForeground}
                  />
                  <Text size="sm" style={styles.flex}>
                    {a.name || a.line1}, {a.city}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        ) : list[0] ? (
          <Text size="sm">
            <Text tone="muted" size="sm">
              {t("deliverTo")}:{" "}
            </Text>
            {list[0].line1}, {list[0].city}
          </Text>
        ) : null}
        <Text size="sm" weight="medium">
          {t("noteLabel")}
        </Text>
        <TextInput
          accessibilityLabel={t("noteLabel")}
          value={note}
          maxLength={500}
          multiline
          onChangeText={setNote}
          placeholder={t("notePlaceholder")}
          placeholderTextColor={colors.mutedForeground}
          style={[
            styles.note,
            { borderColor: colors.input, borderRadius: radius, color: colors.foreground },
          ]}
        />
        <Totals quote={quote} />
        {orderProblems.map((problem) => (
          <Notice key={problem.code} tone={problem.blocking ? "danger" : "warning"}>
            <ProblemText problem={problem} />
          </Notice>
        ))}
        {needsApproval ? (
          <Notice tone="info">
            {t(quote.credit.reason === "OVERDUE" ? "needsApprovalOverdue" : "needsApproval")}
          </Notice>
        ) : null}
        {stage.kind === "unknown" ? <Notice tone="warning">{t("unknownOutcome")}</Notice> : null}
        {stage.kind === "offline" ? <Notice tone="danger">{t("offline")}</Notice> : null}
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Button
          variant="ghost"
          label={t("clear")}
          disabled={busy}
          onPress={() =>
            Alert.alert(t("clearTitle"), undefined, [
              { text: common("cancel"), style: "cancel" },
              {
                text: t("clear"),
                style: "destructive",
                onPress: async () => {
                  const response = await shopCartClear();
                  client.setQueryData(getShopCartRetrieveQueryKey(), response);
                  void query.refetch();
                },
              },
            ])
          }
        />
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  gap: { gap: space[3] },
  gapSm: { gap: space[1] },
  row: { flexDirection: "row", gap: space[3], alignItems: "flex-start" },
  inline: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
  between: { flexDirection: "row", justifyContent: "space-between", gap: space[4] },
  lineFoot: { flexDirection: "row", alignItems: "center", gap: space[2], flexWrap: "wrap" },
  pill: { paddingHorizontal: space[2], paddingVertical: 2, borderRadius: 999 },
  notice: { flexDirection: "row", gap: space[2], padding: space[3], alignItems: "flex-start" },
  option: {
    minHeight: 48,
    borderWidth: 1,
    paddingHorizontal: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  note: {
    minHeight: 80,
    borderWidth: 1,
    padding: space[3],
    fontSize: text.base,
    textAlignVertical: "top",
  },
});
