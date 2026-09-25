import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { PlatformShell } from "./shell";

export default async function PlatformLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("shell");
  return <PlatformShell title={t("platformTitle")}>{children}</PlatformShell>;
}
