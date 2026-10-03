"use client";

import { useTranslations } from "@/lib/i18n/translations";

import { SubNav } from "@/components/shared/sub-nav";

export function OrdersNav() {
  const t = useTranslations("orders.nav");
  return (
    <SubNav
      label={t("label")}
      items={[
        {
          href: "/manage/orders",
          label: t("orders"),
          match: (path) =>
            path === "/manage/orders" || /^\/manage\/orders\/[0-9a-f-]{36}$/.test(path),
        },
        { href: "/manage/orders/shipments", label: t("shipments") },
        { href: "/manage/backorders", label: t("backorders"), prefix: true },
        {
          href: "/manage/settings/policies/orders",
          label: t("settings"),
          permission: "settings.manage",
        },
      ]}
    />
  );
}
