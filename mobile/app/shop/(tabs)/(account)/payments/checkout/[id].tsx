/**
 * One checkout (the web's /shop/payments/checkout/[id]). "Pay now" opens this checkout's payment
 * page in a Chrome Custom Tab, never a web view, so UPI apps can open from it (ADR-061 item 9).
 * The tab's sign-in covers that page only. Whether it was paid comes from the server, read here
 * with the app's own session; never from what the tab reported.
 */
import Feather from "@expo/vector-icons/Feather";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { ActivityIndicator, Alert, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { DocumentButton } from "@/components/shared/document-button";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  shopCheckoutBrowser,
  shopPaymentsReceipt,
  useShopCheckout,
} from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatMoney } from "@/lib/shared/format";
import { space, useTheme } from "@/lib/theme/theme";

const OPEN = new Set(["CREATED", "ATTEMPTED"]);

export default function CheckoutScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const t = useTranslations("shop.pay");
  const tp = useTranslations("providerMessages");
  const { message } = useErrorText();
  const { colors, radius } = useTheme();
  const [busy, setBusy] = useState(false);
  const query = useShopCheckout(id, {
    query: {
      // While it's open the page follows it, as the web's does: the bank's word can come late.
      refetchInterval: (q) => (OPEN.has(q.state.data?.data.status ?? "") ? 3000 : false),
    },
  });
  const checkout = query.data?.data;

  async function pay() {
    setBusy(true);
    try {
      const { url } = (await shopCheckoutBrowser(id)).data;
      // In the app's task: the payment page's "Back to the app" closes the tab.
      await WebBrowser.openBrowserAsync(url, { createTask: false, showTitle: true });
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setBusy(false);
      void query.refetch(); // back in the app: ask the server
    }
  }

  if (isWaiting(query)) {
    return (
      <Screen>
        <ListSkeleton rows={2} />
      </Screen>
    );
  }
  if (isUnsaved(query)) {
    return (
      <Screen>
        <Unsaved />
      </Screen>
    );
  }
  if (failed(query)) {
    return (
      <Screen>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }
  if (!checkout) {
    return (
      <Screen>
        <EmptyState icon="credit-card" title={t("notFound")} />
      </Screen>
    );
  }
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <View style={styles.head}>
        <Text size="2xl" weight="bold">
          {formatMoney(checkout.amount)}
        </Text>
        <Text tone="muted">
          {checkout.invoice_id
            ? t("forBill", { number: checkout.invoice_number })
            : t(`purposes.${checkout.purpose}`)}
        </Text>
      </View>
      {checkout.status === "PAID" ? (
        <Card style={{ backgroundColor: colors.success + "1a", borderColor: "transparent" }}>
          <View accessibilityRole="summary" style={styles.paid}>
            <Feather name="check-circle" size={24} color={colors.successStrong} />
            <Text size="lg" weight="semibold">
              {t("paid")}
            </Text>
          </View>
          <Text size="sm">{t("paidBody", { receipt: checkout.receipt_number })}</Text>
          {checkout.payment_id ? (
            <DocumentButton
              primary
              label={t("receipt")}
              fileName={checkout.receipt_number}
              fetchLink={() => shopPaymentsReceipt(checkout.payment_id ?? "")}
            />
          ) : null}
        </Card>
      ) : checkout.status === "EXPIRED" ? (
        <Card>
          <Text>{t("expired")}</Text>
          <Button label={t("startAgain")} onPress={() => router.back()} />
        </Card>
      ) : (
        <View style={styles.gap}>
          {checkout.awaiting_confirmation ? (
            <View
              accessibilityLiveRegion="polite"
              style={[styles.notice, { backgroundColor: colors.muted, borderRadius: radius }]}
            >
              <ActivityIndicator size="small" color={colors.mutedForeground} />
              <Text size="sm" style={styles.flex}>
                {t("waiting")}
              </Text>
            </View>
          ) : null}
          {checkout.last_error ? (
            // The web's ProviderMessage: our words, then the gateway's own (in English).
            <View
              accessibilityRole="alert"
              style={[
                styles.message,
                { backgroundColor: colors.destructive + "1a", borderRadius: radius },
              ]}
            >
              <Text size="sm">{tp("payment")}</Text>
              <Text size="sm" style={styles.provider}>
                {checkout.last_error}
              </Text>
            </View>
          ) : null}
          <Button
            label={t("payNow", { amount: formatMoney(checkout.amount) })}
            needsInternet
            busy={busy}
            icon={<Feather name="credit-card" size={18} color={colors.primaryForeground} />}
            onPress={() => void pay()}
          />
          <Text tone="muted" size="sm">
            {t("safe")}
          </Text>
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  head: { gap: space[1] },
  gap: { gap: space[3] },
  paid: { flexDirection: "row", alignItems: "center", gap: space[2] },
  notice: { padding: space[3], flexDirection: "row", alignItems: "center", gap: space[2] },
  message: { padding: space[3], gap: 2 },
  provider: { opacity: 0.8 },
});
