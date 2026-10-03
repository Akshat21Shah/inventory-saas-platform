import Feather from "@expo/vector-icons/Feather";
import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useTranslations } from "@/lib/i18n/translations";
import { space, text, TOUCH, useTheme } from "@/lib/theme/theme";

/** Search in either script (ADR-060; smart search when the distributor has it on, server-side). */
export function SearchBox({
  value,
  onChangeText,
  autoFocus,
}: {
  value?: string;
  onChangeText?: (text: string) => void;
  autoFocus?: boolean;
}) {
  const t = useTranslations("shop");
  const { colors, radius } = useTheme();
  const [own, setOwn] = useState("");
  const current = value ?? own;
  return (
    <View
      accessibilityRole="search"
      style={[
        styles.box,
        { borderColor: colors.input, borderRadius: radius, backgroundColor: colors.background },
      ]}
    >
      <Feather name="search" size={20} color={colors.mutedForeground} />
      <TextInput
        accessibilityLabel={t("search")}
        placeholder={t("searchPlaceholder")}
        placeholderTextColor={colors.mutedForeground}
        value={current}
        autoFocus={autoFocus}
        returnKeyType="search"
        onChangeText={onChangeText ?? setOwn}
        onSubmitEditing={() => {
          if (!onChangeText)
            router.push({ pathname: "/shop/search", params: { q: current.trim() } });
        }}
        style={[styles.input, { color: colors.foreground }]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    minHeight: TOUCH,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
    paddingHorizontal: space[3],
  },
  input: { flex: 1, minHeight: TOUCH, fontSize: text.base },
});
