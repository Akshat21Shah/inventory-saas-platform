"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { cn } from "@/lib/utils";

export const POLICY_GROUPS = [
  "tax",
  "invoicing",
  "orders",
  "pricing",
  "retailers",
  "stock",
  "credit_payments",
  "notifications",
  "security",
] as const;

interface Section {
  href: string;
  labelKey: string;
  /** Hidden unless the user has this permission (the server enforces it regardless). */
  permission?: string;
  /** Also current on its sub-pages. */
  prefix?: boolean;
  /** Another page that belongs to this section. */
  also?: string;
  /** Shown only while one of these optional modules is on. */
  features?: string[];
}

const SECTIONS: Section[] = [
  { href: "/manage/settings/business", labelKey: "business" },
  { href: "/manage/settings/branding", labelKey: "branding" },
  // The notifications group opens from Settings → Messages (its "Quiet hours & reminders" tab).
  ...POLICY_GROUPS.filter((group) => group !== "notifications").map((group) => ({
    href: `/manage/settings/policies/${group}`,
    labelKey: `policies.${group}`,
  })),
  { href: "/manage/settings/features", labelKey: "features" },
  {
    href: "/manage/settings/compliance",
    labelKey: "compliance",
    permission: "settings.manage",
    features: ["einvoice", "ewaybill"],
  },
  {
    href: "/manage/settings/online-payments",
    labelKey: "onlinePayments",
    permission: "settings.manage",
    features: ["payments"],
  },
  {
    href: "/manage/settings/notifications",
    labelKey: "notifications",
    permission: "notifications.manage",
    prefix: true,
    also: "/manage/settings/policies/notifications",
  },
  { href: "/manage/settings/staff", labelKey: "staff", permission: "staff.manage" },
  { href: "/manage/settings/roles", labelKey: "roles", permission: "staff.manage" },
  { href: "/manage/audit", labelKey: "audit", permission: "audit.view" },
];

/** Settings sub-navigation: a side list on wide screens, a scrolling row of chips on phones. */
export function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("distributorSettings.nav");
  const pathname = usePathname();
  const { can, feature } = useAuth();
  const sections = SECTIONS.filter(
    (s) =>
      (!s.permission || can(s.permission)) &&
      (!s.features || s.features.some((code) => feature(code))),
  );
  return (
    <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
      <nav aria-label={t("label")} className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:px-0">
        <ul className="flex gap-2 lg:flex-col lg:gap-0.5">
          {sections.map((section) => {
            const active =
              pathname === section.href ||
              pathname === section.also ||
              Boolean(section.prefix && pathname.startsWith(`${section.href}/`));
            return (
              <li key={section.href} className="shrink-0">
                <Link
                  href={section.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-10 items-center rounded-full border px-3 text-sm whitespace-nowrap max-md:min-h-11 lg:rounded-lg lg:border-0",
                    active
                      ? "bg-brand-50 text-brand-900 border-brand-200 font-medium"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {t(section.labelKey)}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
