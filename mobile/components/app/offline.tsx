/**
 * Saying plainly when the phone is offline (ADR-061 item 10): what the screen shows was saved at
 * a time, prices are as last seen, and what needs a connection waits for one.
 */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { StyleSheet, View } from "react-native";

import { EmptyState } from "@/components/shared/states";
import { Text } from "@/components/ui/text";
import { useTranslations } from "@/lib/i18n/translations";
import { useOnline } from "@/lib/offline/online";
import { formatDateTime } from "@/lib/shared/format";
import { space, useTheme } from "@/lib/theme/theme";

/** "You're offline. Showing what was saved at 04-10-2026, 10:42." on top of a screen. */
export function OfflineBanner() {
  const t = useTranslations("app.offline");
  const online = useOnline();
  const client = useQueryClient();
  const { colors, radius } = useTheme();
  // The newest saved data's time; it follows the cache (the saved copy loads after the first draw).
  const saved = useSyncExternalStore(
    (listener) => client.getQueryCache().subscribe(listener),
    () =>
      Math.max(
        0,
        ...client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.dataUpdatedAt),
      ),
  );
  if (online) return null;
  return (
    <View
      accessibilityRole="alert"
      style={[styles.banner, { backgroundColor: colors.warning + "26", borderRadius: radius }]}
    >
      <Feather name="wifi-off" size={18} color={colors.warningStrong} />
      <Text size="sm" style={styles.flex}>
        {saved ? t("banner", { time: formatDateTime(new Date(saved)) }) : t("bannerNothing")}
      </Text>
    </View>
  );
}

/** "as last seen" beside a price while offline. */
export function LastSeen() {
  const t = useTranslations("app.offline");
  if (useOnline()) return null;
  return (
    <Text tone="muted" size="xs">
      {t("lastSeen")}
    </Text>
  );
}

/** Under an action that needs a connection, while there is none. */
export function NeedsInternet() {
  const t = useTranslations("app.offline");
  if (useOnline()) return null;
  return (
    <Text tone="muted" size="sm">
      {t("needsInternet")}
    </Text>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  banner: { padding: space[3], flexDirection: "row", alignItems: "center", gap: space[2] },
});

/** A page that wasn't saved, while offline: it opens once the connection is back. */
export function Unsaved() {
  const t = useTranslations("app.offline");
  return <EmptyState icon="wifi-off" title={t("unsavedTitle")} body={t("unsavedBody")} />;
}
