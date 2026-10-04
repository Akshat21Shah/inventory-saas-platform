/** My payments (the web's /shop/payments): newest first, each with its receipt. */
import { StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { DocumentButton } from "@/components/shared/document-button";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { MoneyText } from "@/components/shared/values";
import { Pager } from "@/components/shop/money";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { shopPaymentsReceipt, useShopPaymentsList } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatDate } from "@/lib/shared/format";
import { useCursor } from "@/lib/shared/pagination";
import { space } from "@/lib/theme/theme";

export default function PaymentsScreen() {
  const t = useTranslations("shop.money");
  const modes = useTranslations("billing.modes");
  const cursor = useCursor();
  const query = useShopPaymentsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <Text size="2xl" weight="bold">
        {t("payments")}
      </Text>
      {isWaiting(query) ? (
        <ListSkeleton rows={3} />
      ) : isUnsaved(query) ? (
        <Unsaved />
      ) : failed(query) ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState icon="credit-card" title={t("noPayments")} />
      ) : (
        rows.map((payment) => (
          <Card key={payment.id}>
            <View style={styles.gap}>
              <MoneyText value={payment.amount} weight="semibold" />
              <Text tone="muted" size="sm">
                {`${formatDate(payment.payment_date)} · ${modes(payment.mode)}`}
                {payment.collected_by_name
                  ? ` · ${t("collectedBy", { name: payment.collected_by_name })}`
                  : ""}
              </Text>
              {payment.status === "BOUNCED" || payment.status === "REVERSED" ? (
                <Text tone="danger" size="sm">
                  {t(`status.${payment.status}`)}
                </Text>
              ) : payment.status === "PENDING_CLEARANCE" ? (
                <Text tone="warning" size="sm">
                  {t("status.PENDING_CLEARANCE")}
                </Text>
              ) : null}
            </View>
            <DocumentButton
              label={t("receipt")}
              fileName={payment.number}
              fetchLink={() => shopPaymentsReceipt(payment.id)}
            />
          </Card>
        ))
      )}
      <Pager pager={cursor.pagination(page)} />
    </Screen>
  );
}

const styles = StyleSheet.create({ gap: { gap: 2, marginBottom: space[1] } });
