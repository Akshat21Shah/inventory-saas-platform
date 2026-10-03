"use client";

import { SubNav } from "@/components/shared/sub-nav";
import { useTranslations } from "@/lib/i18n/translations";

/** Settings → Messages sections. */
export function NotificationsNav() {
  const t = useTranslations("notifyAdmin.nav");
  return (
    <SubNav
      label={t("label")}
      items={[
        { href: "/manage/settings/notifications", label: t("rules") },
        { href: "/manage/settings/notifications/texts", label: t("texts") },
        { href: "/manage/settings/notifications/deliveries", label: t("deliveries") },
        { href: "/manage/settings/notifications/announcements", label: t("announcements") },
        {
          href: "/manage/settings/policies/notifications",
          label: t("settings"),
          permission: "settings.manage",
        },
      ]}
    />
  );
}

export const eventKey = (code: string) => code.replace(".", "_");
