import type { ReactNode } from "react";
import type { Metadata } from "next";
import { getTranslations } from "@/lib/i18n/server";

import { RetailerShell } from "./shell";

export const metadata: Metadata = {
  manifest: "/shop/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "default" },
  icons: { apple: "/shop/icons/icon-192.png" },
};

export default async function RetailerLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("shell");
  return <RetailerShell title={t("shopTitle")}>{children}</RetailerShell>;
}
