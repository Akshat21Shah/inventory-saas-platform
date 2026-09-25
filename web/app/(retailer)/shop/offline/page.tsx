import { WifiOff } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/shared/empty-state";

export default async function OfflinePage() {
  const t = await getTranslations("offline");
  return <EmptyState icon={WifiOff} title={t("title")} description={t("body")} />;
}
