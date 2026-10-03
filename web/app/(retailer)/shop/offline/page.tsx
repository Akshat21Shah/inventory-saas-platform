import { WifiOff } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { getTranslations } from "@/lib/i18n/server";

export default async function OfflinePage() {
  const t = await getTranslations("offline");
  return <EmptyState icon={WifiOff} title={t("title")} description={t("body")} />;
}
