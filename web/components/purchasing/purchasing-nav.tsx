"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/shared/empty-state";
import { SubNav } from "@/components/shared/sub-nav";

/** The Purchasing section (ADR-053, flag ``purchasing``): its tabs, or a word when it's off. */
export function PurchasingLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("purchasing.nav");
  const { feature, me } = useAuth();
  if (me && !feature("purchasing")) {
    return <EmptyState title={t("offTitle")} description={t("offBody")} />;
  }
  return (
    <>
      <SubNav
        label={t("label")}
        items={[{ href: "/manage/purchasing/suppliers", label: t("suppliers"), prefix: true }]}
      />
      {children}
    </>
  );
}
