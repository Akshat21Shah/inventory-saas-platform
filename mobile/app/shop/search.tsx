import { Stack, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";

import { ProductList } from "@/components/shop/product-list";
import { SearchBox } from "@/components/shop/search-box";
import { Text } from "@/components/ui/text";
import { useTranslations } from "@/lib/i18n/translations";
import { space } from "@/lib/theme/theme";

export default function SearchScreen() {
  const t = useTranslations("shop");
  const { q } = useLocalSearchParams<{ q?: string }>();
  const [text, setText] = useState(q ?? "");
  const [search, setSearch] = useState(text.trim());
  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);
  const box = <SearchBox value={text} onChangeText={setText} autoFocus={!q} />;
  return (
    <>
      <Stack.Screen options={{ title: t("searchTitle") }} />
      {search ? (
        <ProductList params={{ search }} header={box} />
      ) : (
        <View style={styles.pad}>
          {box}
          <Text tone="muted" size="sm">
            {t("searchHint")}
          </Text>
        </View>
      )}
    </>
  );
}

const styles = StyleSheet.create({ pad: { padding: space[4], gap: space[4] } });
