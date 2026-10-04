/**
 * Your profile (the web's /shop/account/security): the shop and its distributor, the person's
 * name, the language and signing out. The language applies at once (the web saves it with the
 * name).
 */
import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import { Alert, Pressable, StyleSheet, View } from "react-native";

import { confirm } from "@/components/shared/confirm";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import { authMeUpdate } from "@/lib/api/generated/endpoints/auth/auth";
import { useAuth } from "@/lib/auth/auth-provider";
import { useTranslations } from "@/lib/i18n/translations";
import { formatIndianMobile } from "@/lib/shared/format";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

export default function ProfileScreen() {
  const t = useTranslations("account");
  const tm = useTranslations("shop.money");
  const ta = useTranslations("app.account");
  const auth = useTranslations("auth");
  const common = useTranslations("common");
  const { me, branding, reload, signOut } = useAuth();
  const { message } = useErrorText();
  const { colors, radius } = useTheme();
  const [saving, setSaving] = useState<string | null>(null);
  const [name, setName] = useState(me?.full_name ?? "");
  const [savingName, setSavingName] = useState(false);
  const saveName = async () => {
    setSavingName(true);
    try {
      await authMeUpdate({ full_name: name.trim() });
      await reload();
      Alert.alert(t("saved"));
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setSavingName(false);
    }
  };
  const languages = me?.languages ?? [];
  const choose = async (code: string) => {
    setSaving(code);
    try {
      await authMeUpdate({ preferred_language: code });
      await reload();
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setSaving(null);
    }
  };
  return (
    <Screen>
      <Text size="2xl" weight="bold">
        {tm("profile")}
      </Text>
      <Card>
        <Text size="lg" weight="semibold">
          {me?.retailer?.shop_name ?? ""}
        </Text>
        {me?.retailer?.code ? (
          <Text tone="muted" size="sm">
            {ta("shopCode", { code: me.retailer.code })}
          </Text>
        ) : null}
        {branding ? (
          <Text size="sm">{ta("distributor", { name: branding.display_name })}</Text>
        ) : null}
        {me?.phone ? (
          <Text tone="muted" size="sm">
            {`${t("email")}: ${formatIndianMobile(me.phone)}`}
          </Text>
        ) : null}
      </Card>
      <Card>
        <Input label={t("fullName")} value={name} onChangeText={setName} autoComplete="name" />
        <Button
          label={t("save")}
          needsInternet
          busy={savingName}
          disabled={name.trim() === (me?.full_name ?? "")}
          onPress={() => void saveName()}
        />
      </Card>
      {languages.length > 1 ? (
        <Card>
          <Text weight="semibold">{t("language")}</Text>
          <View accessibilityRole="radiogroup" style={styles.gap}>
            {languages.map((language) => {
              const on = me?.language === language.code;
              return (
                <Pressable
                  key={language.code}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: on, busy: saving === language.code }}
                  disabled={saving !== null}
                  onPress={() => void choose(language.code)}
                  style={[
                    styles.option,
                    { borderColor: on ? colors.primary : colors.border, borderRadius: radius },
                  ]}
                >
                  <Feather
                    name={on ? "check-circle" : "circle"}
                    size={18}
                    color={on ? colors.primary : colors.mutedForeground}
                  />
                  <Text weight={on ? "semibold" : "normal"}>{language.native}</Text>
                </Pressable>
              );
            })}
          </View>
        </Card>
      ) : null}
      <Button
        variant="outline"
        label={auth("signOut")}
        icon={<Feather name="log-out" size={16} color={colors.foreground} />}
        onPress={() =>
          confirm({
            title: auth("signOut"),
            confirmLabel: auth("signOut"),
            cancelLabel: common("cancel"),
            onConfirm: signOut,
          })
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  gap: { gap: space[2] },
  option: {
    minHeight: TOUCH,
    borderWidth: 1,
    paddingHorizontal: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
});
