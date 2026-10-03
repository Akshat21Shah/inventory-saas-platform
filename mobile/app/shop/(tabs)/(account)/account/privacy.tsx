/** Privacy and data (owner addition, ADR-061): the privacy policy, what the app keeps on this
 * phone, and asking the distributor to delete the shop's data. */
import Feather from "@expo/vector-icons/Feather";
import { router } from "expo-router";
import { Linking, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useAppConfig } from "@/lib/api/generated/endpoints/public/public";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

export default function PrivacyScreen() {
  const t = useTranslations("shop.account.privacy");
  const ta = useTranslations("app.privacy");
  const { colors } = useTheme();
  const policy = useAppConfig().data?.data.privacy_policy_url ?? "";
  return (
    <Screen>
      <Text size="2xl" weight="bold">
        {t("title")}
      </Text>
      <Card>
        <Text weight="semibold">{t("policyTitle")}</Text>
        {policy ? (
          <Button
            variant="outline"
            label={t("policy")}
            icon={<Feather name="external-link" size={16} color={colors.foreground} />}
            onPress={() => void Linking.openURL(policy)}
          />
        ) : (
          <Text tone="muted" size="sm">
            {t("noPolicy")}
          </Text>
        )}
      </Card>
      <Card>
        <Text weight="semibold">{ta("phoneTitle")}</Text>
        <Text size="sm">{ta("phoneBody")}</Text>
      </Card>
      <Card>
        <Text weight="semibold">{t("deleteTitle")}</Text>
        <View style={styles.gap}>
          <Text size="sm">{t("deleteBody")}</Text>
          <Text tone="muted" size="sm">
            {t("keptBody")}
          </Text>
        </View>
        <Button
          variant="outline"
          label={t("contact")}
          icon={<Feather name="life-buoy" size={16} color={colors.foreground} />}
          onPress={() => router.push("/shop/account/help")}
        />
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({ gap: { gap: space[2] } });
