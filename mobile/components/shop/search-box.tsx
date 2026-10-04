/**
 * Search in either script (ADR-060; smart search when the distributor has it on, server-side).
 *
 * Two forms:
 * - `SearchEntry` on home and the catalogue: looks like the box and opens the search screen, where
 *   the keyboard comes up at once;
 * - `SearchBox` on the search screen: one input that stays mounted while results change (owner,
 *   checkpoint review), with a clear (×) button; the keyboard closes only on Search, a tap outside
 *   or scrolling the results.
 */
import Feather from "@expo/vector-icons/Feather";
import { router } from "expo-router";
import { forwardRef, useImperativeHandle, useRef } from "react";
import { Keyboard, Pressable, StyleSheet, TextInput, View } from "react-native";

import { Text } from "@/components/ui/text";
import { useTranslations } from "@/lib/i18n/translations";
import { space, text, TOUCH, useTheme } from "@/lib/theme/theme";

function useBoxStyle() {
  const { colors, radius } = useTheme();
  return [
    styles.box,
    { borderColor: colors.input, borderRadius: radius, backgroundColor: colors.background },
  ];
}

export function SearchEntry() {
  const t = useTranslations("shop");
  const { colors } = useTheme();
  const box = useBoxStyle();
  return (
    <Pressable
      accessibilityRole="search"
      accessibilityLabel={t("search")}
      onPress={() => router.push("/shop/search")}
      style={box}
    >
      <Feather name="search" size={20} color={colors.mutedForeground} />
      <Text tone="muted" style={styles.input}>
        {t("searchPlaceholder")}
      </Text>
    </Pressable>
  );
}

export const SearchBox = forwardRef<
  Pick<TextInput, "focus" | "blur">,
  { value: string; onChangeText: (text: string) => void; autoFocus?: boolean }
>(function SearchBox({ value, onChangeText, autoFocus }, ref) {
  const t = useTranslations("shop");
  const ta = useTranslations("app.search");
  const { colors } = useTheme();
  const box = useBoxStyle();
  const input = useRef<TextInput>(null);
  useImperativeHandle(ref, () => ({
    focus: () => input.current?.focus(),
    blur: () => input.current?.blur(),
  }));
  return (
    <View accessibilityRole="search" style={box}>
      <Feather name="search" size={20} color={colors.mutedForeground} />
      <TextInput
        ref={input}
        accessibilityLabel={t("search")}
        placeholder={t("searchPlaceholder")}
        placeholderTextColor={colors.mutedForeground}
        value={value}
        autoFocus={autoFocus}
        autoCorrect={false}
        autoCapitalize="none"
        returnKeyType="search"
        submitBehavior="blurAndSubmit"
        onChangeText={onChangeText}
        onSubmitEditing={() => Keyboard.dismiss()}
        style={[styles.input, { color: colors.foreground }]}
      />
      {value ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={ta("clear")}
          hitSlop={8}
          onPress={() => {
            onChangeText("");
            input.current?.focus();
          }}
          style={styles.clear}
        >
          <Feather name="x" size={20} color={colors.mutedForeground} />
        </Pressable>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  box: {
    minHeight: TOUCH,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
    paddingLeft: space[3],
  },
  input: {
    flex: 1,
    minHeight: TOUCH,
    fontSize: text.base,
    textAlignVertical: "center",
    paddingVertical: 12,
  },
  clear: { width: TOUCH, height: TOUCH, alignItems: "center", justifyContent: "center" },
});
