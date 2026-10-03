import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Keyboard, Pressable, StyleSheet, View, type TextInput } from "react-native";

import { ProductList } from "@/components/shop/product-list";
import { SearchBox } from "@/components/shop/search-box";
import { Text } from "@/components/ui/text";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

/**
 * Search (owner, checkpoint review): the box stays where it is, never re-created, while the
 * results below update as the shop types (after a short pause), so the keyboard stays open.
 */
export default function SearchScreen() {
  const t = useTranslations("shop");
  const { colors } = useTheme();
  const { q } = useLocalSearchParams<{ q?: string }>();
  const [text, setText] = useState(q ?? "");
  const [search, setSearch] = useState(text.trim());
  const box = useRef<Pick<TextInput, "focus" | "blur">>(null);
  // Android raises the keyboard only for focus after the screen has finished opening.
  useFocusEffect(
    useCallback(() => {
      const timer = setTimeout(() => box.current?.focus(), 350);
      return () => clearTimeout(timer);
    }, []),
  );
  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);
  return (
    <View style={[styles.fill, { backgroundColor: colors.background }]}>
      <View style={styles.box}>
        <Text size="2xl" weight="bold">
          {t("searchTitle")}
        </Text>
        <SearchBox ref={box} value={text} onChangeText={setText} />
      </View>
      {search ? (
        <ProductList params={{ search }} />
      ) : (
        <Pressable accessible={false} onPress={Keyboard.dismiss} style={[styles.fill, styles.hint]}>
          <Text tone="muted" size="sm">
            {t("searchHint")}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  box: {
    gap: space[4],
    paddingHorizontal: space[4],
    paddingTop: space[4],
    paddingBottom: space[2],
  },
  hint: { paddingHorizontal: space[4], paddingTop: space[2] },
});
