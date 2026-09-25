import { ShoppingCart } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/shared/empty-state";

export default async function ShopHome() {
  const t = await getTranslations("home");
  return (
    <EmptyState icon={ShoppingCart} title={t("shopEmptyTitle")} description={t("shopEmptyBody")} />
  );
}
