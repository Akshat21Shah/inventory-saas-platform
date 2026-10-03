/**
 * What the shop owes and paying it (the web's components/shop/account.tsx and pay.tsx): amounts,
 * dates and states all come from the server; the app only shows them (thin client).
 */
import Feather from "@expo/vector-icons/Feather";
import { Link, router } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, StyleSheet, View } from "react-native";

import { MoneyText } from "@/components/shared/values";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  shopCheckoutStart,
  useShopAccount,
  useShopHome,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { CheckoutInputRequest, ShopAccount } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { formatMoney } from "@/lib/shared/format";
import { idempotent, newIdempotencyKey } from "@/lib/shared/idempotency";
import type { useCursor } from "@/lib/shared/pagination";
import { space, useTheme } from "@/lib/theme/theme";

/** "You owe ₹X" on the home page, when the shop owes anything; a tap opens the account. */
export function OwedCard() {
  const t = useTranslations("shop.money");
  const { colors, radius } = useTheme();
  const owed = useShopHome().data?.data.outstanding;
  if (!owed || owed.balance === "0.00") return null;
  const credit = owed.balance.startsWith("-");
  const late = owed.overdue !== "0.00";
  return (
    <Link href="/shop/account" asChild>
      <Pressable
        accessibilityRole="link"
        style={StyleSheet.flatten([
          styles.owed,
          {
            borderRadius: radius + 4,
            borderColor: late ? colors.destructive + "66" : colors.border,
            backgroundColor: late ? colors.destructive + "0d" : colors.muted + "66",
          },
        ])}
      >
        <View style={styles.flex}>
          <Text size="sm">{credit ? t("inCredit") : t("youOwe")}</Text>
          <Text size="lg" weight="semibold">
            {formatMoney(credit ? owed.balance.slice(1) : owed.balance)}
          </Text>
          {late ? (
            <Text size="sm" tone="danger">
              {t("overdue", { amount: formatMoney(owed.overdue) })}
            </Text>
          ) : null}
        </View>
        <Feather name="chevron-right" size={20} color={colors.mutedForeground} />
      </Pressable>
    </Link>
  );
}

/** Starts (or re-opens) a checkout and opens its page. The server keeps one active checkout per
 * bill or purpose, so a second tap opens the same one; each tap has its own key. */
function useStartCheckout() {
  const { message } = useErrorText();
  const [busy, setBusy] = useState(false);
  async function start(body: CheckoutInputRequest) {
    setBusy(true);
    try {
      const response = await shopCheckoutStart(body, idempotent(newIdempotencyKey()));
      router.push({ pathname: "/shop/payments/checkout/[id]", params: { id: response.data.id } });
    } catch (error) {
      Alert.alert(message(error)); // e.g. "Payment service is busy, please try again in a minute."
    } finally {
      setBusy(false);
    }
  }
  return { start, busy };
}

/** "Pay ₹X" on a bill, while the distributor takes online payments. */
export function PayBillButton({ invoiceId, balance }: { invoiceId: string; balance: string }) {
  const t = useTranslations("shop.pay");
  const { colors } = useTheme();
  const online = useShopAccount().data?.data.online_payments;
  const { start, busy } = useStartCheckout();
  if (!online || balance === "0.00") return null;
  return (
    <Button
      label={t("payBill", { amount: formatMoney(balance) })}
      busy={busy}
      icon={<Feather name="credit-card" size={16} color={colors.primaryForeground} />}
      onPress={() => void start({ purpose: "INVOICE", invoice_id: invoiceId })}
    />
  );
}

/** On the account page: pay everything owed, or an amount the shop chooses. */
function PayAccountCard({ owed }: { owed: string }) {
  const t = useTranslations("shop.pay");
  const { colors } = useTheme();
  const { start, busy } = useStartCheckout();
  const [amount, setAmount] = useState("");
  const owes = !owed.startsWith("-") && owed !== "0.00";
  return (
    <Card>
      <Text weight="semibold">{t("title")}</Text>
      {owes ? (
        <Button
          label={t("payAll", { amount: formatMoney(owed) })}
          busy={busy}
          icon={<Feather name="credit-card" size={16} color={colors.primaryForeground} />}
          onPress={() => void start({ purpose: "OUTSTANDING" })}
        />
      ) : null}
      <View style={styles.otherRow}>
        <View style={styles.flex}>
          <Input
            label={t("otherAmount")}
            keyboardType="decimal-pad"
            value={amount}
            onChangeText={setAmount}
          />
        </View>
        <Button
          variant="outline"
          label={t("payAmount")}
          disabled={busy || !amount.trim()}
          onPress={() => void start({ purpose: "CUSTOM", amount: amount.trim() })}
        />
      </View>
    </Card>
  );
}

/** What the shop owes, how much is late, its credit, and paying online (the web's account top). */
export function AccountMoney({ account }: { account: ShopAccount }) {
  const t = useTranslations("shop.money");
  const { colors, radius } = useTheme();
  const { position } = account;
  const cell = (label: string, value: string, strong = false, danger = false) => (
    <View style={styles.cell}>
      <Text tone="muted" size="sm">
        {label}
      </Text>
      <MoneyText
        value={value}
        size={strong ? "xl" : "base"}
        weight="semibold"
        tone={danger ? "danger" : "default"}
      />
    </View>
  );
  return (
    <Card>
      <View style={styles.grid}>
        {cell(t("youOwe"), position.owed, true)}
        {cell(t("overdueLabel"), position.overdue, true, position.overdue !== "0.00")}
        {position.unapplied_credit !== "0.00"
          ? cell(t("creditWithUs"), position.unapplied_credit)
          : null}
        {account.available_credit !== null ? cell(t("canOrder"), account.available_credit) : null}
      </View>
      {account.online_payments ? <PayAccountCard owed={position.owed} /> : null}
      {account.orders_blocked_for_overdue ? (
        <Text
          size="sm"
          style={[
            styles.notice,
            { backgroundColor: colors.destructive + "1a", borderRadius: radius },
          ]}
        >
          {t("blocked")}
        </Text>
      ) : account.overdue_bills ? (
        <Text
          size="sm"
          style={[styles.notice, { backgroundColor: colors.warning + "26", borderRadius: radius }]}
        >
          {t("overdueBills", { count: account.overdue_bills })}
        </Text>
      ) : null}
    </Card>
  );
}

/** Newer / Older, as the web's lists of bills and payments (`useCursor` is the web's). */
export function Pager({
  pager,
}: {
  pager: ReturnType<ReturnType<typeof useCursor>["pagination"]>;
}) {
  const t = useTranslations("shop.money");
  if (!pager) return null;
  return (
    <View style={styles.pager}>
      <Button
        variant="outline"
        label={t("newer")}
        disabled={!pager.hasPrevious}
        onPress={pager.onPrevious}
      />
      <Button
        variant="outline"
        label={t("older")}
        disabled={!pager.hasNext}
        onPress={pager.onNext}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  owed: {
    minHeight: 56,
    borderWidth: 1,
    padding: space[4],
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
  },
  grid: { flexDirection: "row", flexWrap: "wrap", rowGap: space[3] },
  cell: { width: "50%", gap: 2 },
  otherRow: { flexDirection: "row", alignItems: "flex-end", gap: space[2] },
  notice: { padding: space[3] },
  pager: { flexDirection: "row", justifyContent: "space-between" },
});
