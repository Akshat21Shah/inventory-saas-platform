import { StyleSheet, View } from "react-native";

import { Text } from "@/components/ui/text";
import type { ShopHistory } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

import { StatusBadge } from "./status-badge";
import { DateText } from "./values";

function detail(entry: ShopHistory): Record<string, unknown> {
  return entry.payload && typeof entry.payload === "object"
    ? (entry.payload as Record<string, unknown>)
    : {};
}

/** What happened to an order, newest first, in plain words (the web's OrderTimeline). */
export function OrderTimeline({ entries }: { entries: readonly ShopHistory[] }) {
  const t = useTranslations("orderEvents");
  const s = useTranslations("orderStatus");
  const { colors } = useTheme();
  return (
    <View style={[styles.list, { borderLeftColor: colors.border }]} accessibilityLabel={t("title")}>
      {[...entries].reverse().map((entry) => {
        const data = detail(entry);
        const toFollow = typeof data.items_to_follow === "number" ? data.items_to_follow : 0;
        const shipment = typeof data.shipment === "string" ? data.shipment : "";
        const via = entry.event === "DELIVER" && typeof data.via === "string" ? data.via : "";
        return (
          <View key={entry.id} style={styles.item}>
            <View style={[styles.dot, { backgroundColor: colors.primary }]} />
            <View style={styles.inline}>
              <Text size="sm" weight="medium">
                {t.has(entry.event) ? t(entry.event) : entry.event}
              </Text>
              {shipment ? (
                <Text size="sm" tone="muted">
                  {shipment}
                </Text>
              ) : null}
              <StatusBadge status={entry.to_status} labels="orderStatus" />
              {entry.to_status === "PARTLY_DELIVERED" && toFollow ? (
                <Text tone="muted" size="xs">
                  {s("toFollow", { count: toFollow })}
                </Text>
              ) : null}
            </View>
            <DateText value={entry.created_at} withTime tone="muted" size="xs" />
            {via && via !== "STAFF" && t.has(`deliveredVia.${via}`) ? (
              <Text size="sm">{t(`deliveredVia.${via}`)}</Text>
            ) : null}
            {entry.note ? <Text size="sm">{entry.note}</Text> : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { borderLeftWidth: 1, paddingLeft: space[4], gap: space[4] },
  item: { gap: space[1] },
  dot: {
    position: "absolute",
    left: -space[4] - 5.5,
    top: 6,
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  inline: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
});
