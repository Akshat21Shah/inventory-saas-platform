import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";

export default async function DistributorHome() {
  const t = await getTranslations();
  return (
    <>
      <PageHeader title={t("nav.dashboard")} />
      <EmptyState
        title={t("home.distributorEmptyTitle")}
        description={t("home.distributorEmptyBody")}
      />
    </>
  );
}
