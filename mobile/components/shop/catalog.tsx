import Feather from "@expo/vector-icons/Feather";
import { Link } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ListSkeleton } from "@/components/shared/states";
import { Text } from "@/components/ui/text";
import { useShopBrands, useShopCategories } from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopCategory } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { isUnsaved, isWaiting } from "@/lib/offline/online";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

import { OnHoldNotice } from "./product";
import { ProductList } from "./product-list";
import { SearchEntry } from "./search-box";

const childrenOf = (c: ShopCategory) => c.children as unknown as ShopCategory[];

function findCategory(
  nodes: ShopCategory[],
  id: string,
  trail: ShopCategory[] = [],
): { node: ShopCategory; trail: ShopCategory[] } | null {
  for (const node of nodes) {
    if (node.id === id) return { node, trail };
    const found = findCategory(childrenOf(node), id, [...trail, node]);
    if (found) return found;
  }
  return null;
}

export function CategoryTiles({ categories }: { categories: ShopCategory[] }) {
  const t = useTranslations("shop");
  const { colors, radius } = useTheme();
  return (
    <View style={styles.tiles}>
      {categories.map((category) => (
        <Link key={category.id} href={`/shop/catalog/${category.id}`} asChild>
          <Pressable
            accessibilityRole="link"
            style={StyleSheet.flatten([
              styles.tile,
              { borderColor: colors.border, borderRadius: radius },
            ])}
          >
            <View style={styles.flex}>
              <Text weight="medium">{category.name}</Text>
              <Text tone="muted" size="xs">
                {t("productCount", { count: category.product_count })}
              </Text>
            </View>
            <Feather name="chevron-right" size={16} color={colors.mutedForeground} />
          </Pressable>
        </Link>
      ))}
    </View>
  );
}

function BrandFilter({
  categoryId,
  value,
  onChange,
}: {
  categoryId?: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const t = useTranslations("shop");
  const { colors } = useTheme();
  const brands = useShopBrands({ category: categoryId }).data?.data ?? [];
  if (brands.length < 2) return null;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      accessibilityLabel={t("brandFilter")}
      contentContainerStyle={styles.chips}
    >
      {[{ id: "", name: t("allBrands") }, ...brands].map((brand) => {
        const on = value === brand.id;
        return (
          <Pressable
            key={brand.id || "all"}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(brand.id)}
            style={[
              styles.chip,
              {
                borderColor: on ? colors.primary : colors.border,
                backgroundColor: on ? colors.primary : "transparent",
              },
            ]}
          >
            <Text size="sm" weight="medium" tone={on ? "onPrimary" : "default"}>
              {brand.name}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/** All products, or one category's: its sub-categories, a brand filter and its products. */
export function CatalogScreen({ categoryId }: { categoryId?: string }) {
  const t = useTranslations("shop");
  const categories = useShopCategories();
  const [brand, setBrand] = useState("");
  if (isWaiting(categories)) {
    return (
      <View style={styles.pad}>
        <ListSkeleton />
      </View>
    );
  }
  if (isUnsaved(categories)) {
    return (
      <View style={styles.pad}>
        <Unsaved />
      </View>
    );
  }
  const tree = categories.data?.data ?? [];
  const found = categoryId ? findCategory(tree, categoryId) : null;
  if (categoryId && !categories.error && !found) {
    return <EmptyState icon="folder" title={t("categoryGoneTitle")} body={t("categoryGoneBody")} />;
  }
  const children = found ? childrenOf(found.node) : tree;
  return (
    <ProductList
      params={{ category: categoryId, brand: brand || undefined }}
      header={
        <>
          <Text size="2xl" weight="bold">
            {found ? found.node.name : t("catalogTitle")}
          </Text>
          <OnHoldNotice />
          <SearchEntry />
          {children.length ? <CategoryTiles categories={children} /> : null}
          <BrandFilter categoryId={categoryId} value={brand} onChange={setBrand} />
        </>
      }
    />
  );
}

const styles = StyleSheet.create({
  pad: { padding: space[4] },
  flex: { flex: 1 },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: space[3] },
  tile: {
    flexGrow: 1,
    flexBasis: "45%",
    minHeight: 64,
    borderWidth: 1,
    padding: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  chips: { gap: space[2] },
  chip: {
    minHeight: TOUCH,
    paddingHorizontal: space[4],
    borderWidth: 1,
    borderRadius: 999,
    justifyContent: "center",
  },
});
