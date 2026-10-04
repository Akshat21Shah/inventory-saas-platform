/** Notifications (the web's /shop/notifications): the shop's messages, newest first; unread ones
 * stand out; opening one marks it read and goes to its page (an order, a bill, payments). */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { refreshNotifications } from "@/components/app/push-setup";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { DateText } from "@/components/shared/values";
import { Pager } from "@/components/shop/money";
import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  shopNotificationsMarkAllRead,
  shopNotificationsMarkRead,
  useShopNotifications,
  useShopNotificationsUnreadCount,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { InboxItem } from "@/lib/api/generated/model";
import { appHref } from "@/lib/app-href";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { useCursor } from "@/lib/shared/pagination";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

export default function NotificationsScreen() {
  const t = useTranslations("notifications");
  const client = useQueryClient();
  const { colors, radius } = useTheme();
  const [show, setShow] = useState<"all" | "unread">("all");
  const cursor = useCursor();
  const list = useShopNotifications({
    cursor: cursor.cursor,
    ...(show === "unread" ? { unread: true } : {}),
  });
  const unread = useShopNotificationsUnreadCount().data?.data.unread ?? 0;
  const [busy, setBusy] = useState(false);
  const page = list.data?.data;

  const open = async (item: InboxItem) => {
    if (!item.is_read) {
      await shopNotificationsMarkRead(item.id).catch(() => undefined);
      refreshNotifications(client);
    }
    if (item.path) router.push(appHref(item.path) as never);
  };

  const readAll = async () => {
    setBusy(true);
    try {
      await shopNotificationsMarkAllRead();
      refreshNotifications(client);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen refreshing={list.isRefetching} onRefresh={() => void list.refetch()}>
      <View style={styles.head}>
        <Text size="2xl" weight="bold">
          {t("title")}
        </Text>
        <Text tone="muted" size="sm">
          {unread ? t("unreadCount", { count: unread }) : t("allRead")}
        </Text>
      </View>
      <Button
        variant="outline"
        label={t("markAllRead")}
        busy={busy}
        disabled={!unread}
        icon={<Feather name="check-square" size={16} color={colors.foreground} />}
        onPress={() => void readAll()}
      />
      <View
        accessibilityRole="tablist"
        style={[styles.tabs, { backgroundColor: colors.muted, borderRadius: radius }]}
      >
        {(["all", "unread"] as const).map((value) => {
          const on = show === value;
          return (
            <Pressable
              key={value}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              onPress={() => {
                setShow(value);
                cursor.reset();
              }}
              style={[
                styles.tab,
                {
                  borderRadius: radius - 2,
                  backgroundColor: on ? colors.background : "transparent",
                },
              ]}
            >
              <Text size="sm" weight={on ? "medium" : "normal"}>
                {t(value)}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {isWaiting(list) ? (
        <ListSkeleton />
      ) : isUnsaved(list) ? (
        <Unsaved />
      ) : failed(list) ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !page?.results.length ? (
        <EmptyState
          icon="bell-off"
          title={show === "unread" ? t("emptyUnread") : t("empty")}
          body={t("emptyBody")}
        />
      ) : (
        <View style={[styles.list, { borderColor: colors.border, borderRadius: radius + 4 }]}>
          {page.results.map((item, index) => (
            <Pressable
              key={item.id}
              accessibilityRole="button"
              accessibilityLabel={`${item.title}${item.is_read ? "" : ` (${t("unread")})`}`}
              onPress={() => void open(item)}
              style={[
                styles.item,
                index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
                !item.is_read && { backgroundColor: colors.brand50 },
              ]}
            >
              <View
                style={[
                  styles.dot,
                  { backgroundColor: item.is_read ? "transparent" : colors.brand600 },
                ]}
              />
              <View style={styles.flex}>
                <Text weight={item.is_read ? "normal" : "semibold"}>{item.title}</Text>
                <Text tone="muted" size="sm">
                  {item.body}
                </Text>
                <DateText value={item.created_at} withTime tone="muted" size="xs" />
              </View>
            </Pressable>
          ))}
        </View>
      )}
      <Pager pager={cursor.pagination(page)} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, gap: 2 },
  head: { gap: space[1] },
  tabs: { flexDirection: "row", padding: 3, alignSelf: "flex-start" },
  tab: {
    minHeight: TOUCH,
    minWidth: TOUCH,
    paddingHorizontal: space[4],
    alignItems: "center",
    justifyContent: "center",
  },
  list: { borderWidth: 1, overflow: "hidden" },
  item: { minHeight: TOUCH, padding: space[4], flexDirection: "row", gap: space[3] },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
});
