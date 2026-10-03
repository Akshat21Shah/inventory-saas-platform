import { Stack, useLocalSearchParams } from "expo-router";

import { CatalogScreen } from "@/components/shop/catalog";
import { useTranslations } from "@/lib/i18n/translations";

export default function CategoryScreen() {
  const { categoryId } = useLocalSearchParams<{ categoryId: string }>();
  const t = useTranslations("nav");
  return (
    <>
      <Stack.Screen options={{ title: t("catalog") }} />
      <CatalogScreen categoryId={categoryId} />
    </>
  );
}
