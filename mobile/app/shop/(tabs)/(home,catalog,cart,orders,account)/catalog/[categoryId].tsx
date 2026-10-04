import { useLocalSearchParams } from "expo-router";

import { CatalogScreen } from "@/components/shop/catalog";

export default function CategoryScreen() {
  const { categoryId } = useLocalSearchParams<{ categoryId: string }>();
  return <CatalogScreen categoryId={categoryId} />;
}
