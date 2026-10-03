/** My bills (the web's /shop/invoices): to pay, overdue or paid, newest first. */
import { Link } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { MoneyText } from "@/components/shared/values";
import { Pager } from "@/components/shop/money";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopInvoicesList } from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopInvoicesListState } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatDate } from "@/lib/shared/format";
import { useCursor } from "@/lib/shared/pagination";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

const STATES: ShopInvoicesListState[] = ["unpaid", "overdue", "paid"];

export default function BillsScreen() {
  const t = useTranslations("shop.money");
  const { colors, radius } = useTheme();
  const [state, setState] = useState<ShopInvoicesListState>("unpaid");
  const cursor = useCursor();
  const query = useShopInvoicesList({ state, cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <Text size="2xl" weight="bold">
        {t("bills")}
      </Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.tabs}
      >
        <View accessibilityRole="tablist" accessibilityLabel={t("bills")} style={styles.tabs}>
          {STATES.map((value) => {
            const on = state === value;
            return (
              <Pressable
                key={value}
                accessibilityRole="tab"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  setState(value);
                  cursor.reset();
                }}
                style={[
                  styles.tab,
                  {
                    borderColor: on ? colors.brand200 : colors.border,
                    backgroundColor: on ? colors.brand50 : colors.background,
                  },
                ]}
              >
                <Text size="sm" weight={on ? "medium" : "normal"}>
                  {t(`state.${value}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
      {isWaiting(query) ? (
        <ListSkeleton rows={3} />
      ) : isUnsaved(query) ? (
        <Unsaved />
      ) : failed(query) ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState icon="file-text" title={t(`noBills.${state}`)} />
      ) : (
        <View style={[styles.list, { borderColor: colors.border, borderRadius: radius + 4 }]}>
          {rows.map((bill, index) => (
            <Link key={bill.id} href={`/shop/invoices/${bill.id}`} asChild>
              <Pressable
                accessibilityRole="link"
                style={StyleSheet.flatten([
                  styles.row,
                  index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
                ])}
              >
                <View style={styles.flex}>
                  <Text weight="medium">{bill.number}</Text>
                  <Text tone="muted" size="sm">
                    {formatDate(bill.invoice_date)}
                    {bill.days_overdue > 0 ? (
                      <Text tone="danger" size="sm">
                        {` · ${t("daysLate", { days: bill.days_overdue })}`}
                      </Text>
                    ) : bill.balance_due !== "0.00" ? (
                      ` · ${t("dueOn", { date: formatDate(bill.due_date) })}`
                    ) : null}
                  </Text>
                </View>
                <View style={styles.end}>
                  <MoneyText
                    value={bill.balance_due !== "0.00" ? bill.balance_due : bill.grand_total}
                    weight="semibold"
                  />
                  <StatusBadge status={bill.payment_status} />
                </View>
              </Pressable>
            </Link>
          ))}
        </View>
      )}
      <Pager pager={cursor.pagination(page)} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  tabs: { flexDirection: "row", gap: space[2] },
  tab: {
    minHeight: TOUCH,
    paddingHorizontal: space[4],
    borderWidth: 1,
    borderRadius: 999,
    justifyContent: "center",
  },
  list: { borderWidth: 1 },
  row: {
    minHeight: 64,
    padding: space[4],
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
  },
  end: { alignItems: "flex-end", gap: 4 },
});
