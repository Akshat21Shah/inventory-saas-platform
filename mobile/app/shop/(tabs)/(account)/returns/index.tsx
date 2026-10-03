/** Returns (owner, checkpoint review item 5): every return the shop asked for, newest first, each
 * opening its bill, where it can be withdrawn while it waits (the web shows them on the bill). */
import Feather from "@expo/vector-icons/Feather";
import { Link } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Pager } from "@/components/shop/money";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopReturnRequestsList } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatDate, formatQty } from "@/lib/shared/format";
import { useCursor } from "@/lib/shared/pagination";
import { space, useTheme } from "@/lib/theme/theme";

export default function ReturnsScreen() {
  const t = useTranslations("shop.returns");
  const tm = useTranslations("shop.money");
  const { colors, radius } = useTheme();
  const cursor = useCursor();
  const query = useShopReturnRequestsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <Text size="2xl" weight="bold">
        {t("heading")}
      </Text>
      {isWaiting(query) ? (
        <ListSkeleton rows={3} />
      ) : isUnsaved(query) ? (
        <Unsaved />
      ) : failed(query) ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState icon="rotate-ccw" title={t("none")} body={t("noneBody")} />
      ) : (
        <View style={[styles.list, { borderColor: colors.border, borderRadius: radius + 4 }]}>
          {rows.map((request, index) => (
            <Link key={request.id} href={`/shop/invoices/${request.invoice.id}`} asChild>
              <Pressable
                accessibilityRole="link"
                style={StyleSheet.flatten([
                  styles.row,
                  index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
                ])}
              >
                <View style={styles.flex}>
                  <View style={styles.between}>
                    <Text weight="medium">{request.number}</Text>
                    <StatusBadge status={request.status} labels="shopReturnStatus" />
                  </View>
                  <Text tone="muted" size="sm">
                    {`${formatDate(request.created_at)} · ${tm("billHeading", { number: request.invoice.number })}`}
                  </Text>
                  <Text tone="muted" size="sm">
                    {request.lines
                      .map((line) => `${formatQty(line.quantity)} ${line.description}`)
                      .join(", ")}
                  </Text>
                  {request.status === "REJECTED" && request.decision_note ? (
                    <Text size="sm">{t("why", { reason: request.decision_note })}</Text>
                  ) : null}
                  {request.credit_note ? (
                    <Text size="sm">{t("credited", { number: request.credit_note.number })}</Text>
                  ) : null}
                </View>
                <Feather name="chevron-right" size={20} color={colors.mutedForeground} />
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
  flex: { flex: 1, gap: 2 },
  list: { borderWidth: 1 },
  row: { padding: space[4], flexDirection: "row", alignItems: "center", gap: space[3] },
  between: { flexDirection: "row", justifyContent: "space-between", gap: space[2] },
});
