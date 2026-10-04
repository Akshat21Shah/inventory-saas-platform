/**
 * Push inside the signed-in shop (ADR-061 item 7): the channels in the shop's language, what a
 * message does while the app is open, this phone registered with the server, and a tapped message
 * opening its page (an order, a bill, payments), marked read, as the inbox does.
 */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as Notifications from "expo-notifications";
import { router } from "expo-router";
import { useEffect, useRef } from "react";

import { shopNotificationsMarkRead } from "@/lib/api/generated/endpoints/shop/shop";
import { appHref } from "@/lib/app-href";
import { useAuth } from "@/lib/auth/auth-provider";
import { useTranslations } from "@/lib/i18n/translations";
import {
  followTokenChanges,
  foregroundBehaviour,
  loadSoundSetting,
  registerThisPhone,
  setUpChannels,
} from "@/lib/push/push";

/** Refetch the bell and the inbox (a message arrived, or some were read): the web's helper. */
export function refreshNotifications(client: QueryClient) {
  void client.invalidateQueries({
    predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/v1/shop/notifications"),
  });
}

Notifications.setNotificationHandler({ handleNotification: async () => foregroundBehaviour() });

export function PushSetup() {
  const t = useTranslations("app.notifications.channels");
  const { me } = useAuth();
  const client = useQueryClient();
  const handled = useRef<string | null>(null);
  const response = Notifications.useLastNotificationResponse();
  const tenant = me?.tenant?.slug ?? "";

  // The channels' names follow the shop's language.
  const names = { orders: t("orders"), money: t("money"), offers: t("offers") };
  const key = `${names.orders}|${names.money}|${names.offers}`;
  useEffect(() => {
    void setUpChannels(names).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` stands for the three names
  }, [key]);

  useEffect(() => {
    void loadSoundSetting();
    // Signed in: this phone gets the shop's messages (asking for permission once).
    void registerThisPhone().catch(() => undefined);
    const stopTokens = followTokenChanges();
    const received = Notifications.addNotificationReceivedListener(() =>
      refreshNotifications(client),
    );
    return () => {
      stopTokens();
      received.remove();
    };
  }, [client]);

  useEffect(() => {
    // A tapped message (also the one that started the app): its page, if it's this distributor's.
    if (!response || response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const id = response.notification.request.identifier;
    if (handled.current === id) return;
    handled.current = id;
    const data = (response.notification.request.content.data ?? {}) as Record<string, string>;
    if (data.tenant && data.tenant !== tenant) return; // signed in to another distributor now
    if (data.notification) {
      void shopNotificationsMarkRead(data.notification)
        .catch(() => undefined)
        .then(() => refreshNotifications(client));
    }
    router.push(appHref(data.path || "/shop/notifications") as never);
  }, [response, tenant, client]);

  return null;
}
