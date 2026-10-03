import Feather from "@expo/vector-icons/Feather";
import { Link } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";

import { StatusBadge } from "@/components/shared/status-badge";
import { DateText, MoneyText } from "@/components/shared/values";
import { Text } from "@/components/ui/text";
import type { ShopOrderRow } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

/** An order's status, with "n items to follow" when partly delivered (ADR-045). */
export function OrderStatus({ status, itemsToFollow }: { status: string; itemsToFollow?: number }) {
  const t = useTranslations("orderStatus");
  return (
    <View style={styles.inline}>
      <StatusBadge status={status} labels="orderStatus" />
      {status === "PARTLY_DELIVERED" && itemsToFollow ? (
        <Text tone="muted" size="xs">
          {t("toFollow", { count: itemsToFollow })}
        </Text>
      ) : null}
    </View>
  );
}

export function OrderRowLink({ order }: { order: ShopOrderRow }) {
  const t = useTranslations("shop.orders");
  const { colors, radius } = useTheme();
  return (
    <Link href={`/shop/orders/${order.id}`} asChild>
      <Pressable
        accessibilityRole="link"
        style={StyleSheet.flatten([
          styles.row,
          { borderColor: colors.border, borderRadius: radius },
        ])}
      >
        <View style={styles.body}>
          <View style={styles.inline}>
            <Text weight="medium">{order.number}</Text>
            <OrderStatus status={order.status} itemsToFollow={order.items_to_follow} />
          </View>
          <Text tone="muted" size="xs">
            <DateText value={order.placed_at} tone="muted" size="xs" /> ·{" "}
            {t("items", { count: order.line_count })}
            {order.placed_by_label ? ` · ${t("placedBy", { name: order.placed_by_label })}` : ""}
          </Text>
        </View>
        <MoneyText value={order.grand_total} weight="semibold" />
        <Feather name="chevron-right" size={18} color={colors.mutedForeground} />
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 64,
    borderWidth: 1,
    padding: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
  },
  body: { flex: 1, gap: space[1] },
  inline: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
});
