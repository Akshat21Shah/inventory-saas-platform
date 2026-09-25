import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";

export default async function PlatformHome() {
  const t = await getTranslations();
  return (
    <>
      <PageHeader title={t("nav.dashboard")} />
      <EmptyState title={t("home.platformEmptyTitle")} description={t("home.platformEmptyBody")} />
    </>
  );
}
