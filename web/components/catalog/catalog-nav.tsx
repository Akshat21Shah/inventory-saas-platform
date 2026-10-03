"use client";

import { useTranslations } from "@/lib/i18n/translations";
import type { ReactNode } from "react";

import { SubNav } from "@/components/shared/sub-nav";

const OTHERS = ["/manage/products/categories", "/manage/products/brands", "/manage/products/units"];

export function CatalogLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("catalog.nav");
  return (
    <>
      <SubNav
        label={t("label")}
        items={[
          {
            href: "/manage/products",
            label: t("products"),
            match: (path) =>
              path.startsWith("/manage/products") && !OTHERS.some((o) => path.startsWith(o)),
          },
          { href: "/manage/products/categories", label: t("categories") },
          { href: "/manage/products/brands", label: t("brands") },
          { href: "/manage/products/units", label: t("units") },
        ]}
      />
      {children}
    </>
  );
}
