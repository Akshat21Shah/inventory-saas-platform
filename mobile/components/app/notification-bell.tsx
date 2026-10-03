import Feather from "@expo/vector-icons/Feather";
import { router } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";

import { Text } from "@/components/ui/text";
import { useShopNotificationsUnreadCount } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { TOUCH, useTheme } from "@/lib/theme/theme";

/** The web's bell, in every header (owner, checkpoint review item 3): the unread count, refreshed
 * every minute, when a message arrives and when the app comes back; a tap opens Notifications. */
export function NotificationBell() {
  const t = useTranslations("notifications");
  const { colors } = useTheme();
  const unread =
    useShopNotificationsUnreadCount({ query: { refetchInterval: 60_000 } }).data?.data.unread ?? 0;
  const label = unread ? t("bellUnread", { count: unread }) : t("bell");
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={4}
      onPress={() => router.push("/shop/notifications")}
      style={styles.bell}
    >
      <Feather name="bell" size={22} color={colors.primaryForeground} />
      {unread ? (
        <View style={[styles.count, { backgroundColor: colors.destructive }]}>
          <Text size="xs" weight="semibold" tone="onPrimary" style={styles.countText}>
            {unread > 99 ? "99+" : String(unread)}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bell: { width: TOUCH, height: TOUCH, alignItems: "center", justifyContent: "center" },
  count: {
    position: "absolute",
    top: 4,
    right: 2,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 4,
    alignItems: "center",
    justifyContent: "center",
  },
  countText: { fontSize: 11, lineHeight: 14 },
});
