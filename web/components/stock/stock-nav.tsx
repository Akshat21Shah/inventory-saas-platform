"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { SubNav } from "@/components/shared/sub-nav";

export function StockLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("stock.nav");
  return (
    <>
      <SubNav
        label={t("label")}
        items={[
          {
            href: "/manage/stock",
            label: t("overview"),
            // The overview and each product's stock page.
            match: (path) =>
              path === "/manage/stock" || /^\/manage\/stock\/[0-9a-f-]{36}$/.test(path),
          },
          { href: "/manage/stock/inwards", label: t("receipts"), prefix: true },
          { href: "/manage/stock/adjustments", label: t("adjustments"), prefix: true },
          { href: "/manage/stock/alerts", label: t("alerts") },
          { href: "/manage/stock/movements", label: t("movements") },
          { href: "/manage/reports/low-stock", label: t("lowStock"), permission: "reports.stock" },
          {
            href: "/manage/reports/stock-valuation",
            label: t("valuation"),
            permission: "costs.view",
          },
          { href: "/manage/settings/policies/stock", label: t("settings") },
        ]}
      />
      {children}
    </>
  );
}
