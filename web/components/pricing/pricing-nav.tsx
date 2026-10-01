"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { SubNav } from "@/components/shared/sub-nav";

export function PricingLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pricing.nav");
  return (
    <>
      <SubNav
        label={t("label")}
        items={[
          { href: "/manage/pricing/price-lists", label: t("priceLists"), prefix: true },
          { href: "/manage/pricing/special-prices", label: t("specialPrices") },
          { href: "/manage/pricing/discounts", label: t("discounts"), prefix: true },
          {
            href: "/manage/pricing/free-goods",
            label: t("freeGoods"),
            prefix: true,
            features: ["free_goods"],
          },
          { href: "/manage/pricing/report", label: t("report") },
          { href: "/manage/settings/policies/pricing", label: t("settings") },
        ]}
      />
      {children}
    </>
  );
}
