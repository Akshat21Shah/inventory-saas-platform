/**
 * Required updates (ADR-061 item 6): when the server refuses this version (426) or the app's
 * settings say it is older than the minimum, one screen asks the person to update.
 */
import Feather from "@expo/vector-icons/Feather";
import { useEffect, useState, type ReactNode } from "react";
import { Linking, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { appConfig } from "@/lib/api/generated/endpoints/public/public";
import { APP_VERSION, APPLICATION_ID } from "@/lib/config";
import { updateRequired } from "@/lib/events";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";
import { isOlder } from "@/lib/version";

export const PLAY_STORE_URL = `https://play.google.com/store/apps/details?id=${APPLICATION_ID}`;

export function UpdateGate({ children }: { children: ReactNode }) {
  const [blocked, setBlocked] = useState(false);
  useEffect(() => updateRequired.listen(() => setBlocked(true)), []);
  useEffect(() => {
    appConfig()
      .then(({ data }) => {
        if (isOlder(APP_VERSION, data.min_version)) setBlocked(true);
      })
      .catch(() => undefined); // offline: the next request tells
  }, []);
  return blocked ? <UpdateScreen /> : children;
}

export function UpdateScreen() {
  const t = useTranslations("app.update");
  const { colors } = useTheme();
  return (
    <Screen edges={["top", "bottom"]} scroll={false}>
      <View style={styles.centre}>
        <Feather name="download" size={48} color={colors.primary} />
        <Text size="2xl" weight="bold" style={styles.text}>
          {t("title")}
        </Text>
        <Text tone="muted" style={styles.text}>
          {t("body")}
        </Text>
        <Button label={t("button")} onPress={() => void Linking.openURL(PLAY_STORE_URL)} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  centre: { flex: 1, justifyContent: "center", alignItems: "center", gap: space[4] },
  text: { textAlign: "center" },
});
