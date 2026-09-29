import type { QueryClient } from "@tanstack/react-query";

import {
  notificationsMarkAllRead,
  notificationsMarkRead,
  useNotificationsInbox,
  useNotificationsUnreadCount,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import {
  shopNotificationsMarkAllRead,
  shopNotificationsMarkRead,
  useShopNotifications,
  useShopNotificationsUnreadCount,
} from "@/lib/api/generated/endpoints/shop/shop";

/** Staff and shops have the same inbox on different routes (the server scopes both to the
 * signed-in person). */
export type InboxScope = "staff" | "shop";

export const INBOX = {
  staff: {
    href: "/manage/notifications",
    useList: useNotificationsInbox,
    useUnread: useNotificationsUnreadCount,
    markRead: notificationsMarkRead,
    markAllRead: notificationsMarkAllRead,
  },
  shop: {
    href: "/shop/notifications",
    useList: useShopNotifications,
    useUnread: useShopNotificationsUnreadCount,
    markRead: shopNotificationsMarkRead,
    markAllRead: shopNotificationsMarkAllRead,
  },
} as const;

/** Refetch the bell and the inbox (a new message arrived, or some were read). */
export function refreshNotifications(client: QueryClient) {
  void client.invalidateQueries({
    predicate: (q) => {
      const key = String(q.queryKey[0] ?? "");
      return (
        key.startsWith("/api/v1/notifications") || key.startsWith("/api/v1/shop/notifications")
      );
    },
  });
}
