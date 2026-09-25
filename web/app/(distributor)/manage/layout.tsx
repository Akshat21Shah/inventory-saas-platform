import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { DistributorShell } from "./shell";

export default async function DistributorLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("shell");
  return <DistributorShell title={t("distributorTitle")}>{children}</DistributorShell>;
}
