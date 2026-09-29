"use client";

import {
  Building,
  Flag,
  Headset,
  LayoutDashboard,
  MessageSquare,
  Percent,
  ScrollText,
  Settings,
  Tags,
} from "lucide-react";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/auth/account-menu";
import { RequireArea } from "@/components/auth/require-area";
import { SidebarShell, type NavItem } from "@/components/shared/app-shell";

const ITEMS: NavItem[] = [
  { href: "/platform", labelKey: "dashboard", icon: LayoutDashboard },
  { href: "/platform/tenants", labelKey: "tenants", icon: Building },
  { href: "/platform/plans", labelKey: "plans", icon: Tags },
  { href: "/platform/feature-flags", labelKey: "featureFlags", icon: Flag },
  { href: "/platform/tax-rates", labelKey: "taxRates", icon: Percent },
  { href: "/platform/impersonations", labelKey: "impersonations", icon: Headset },
  { href: "/platform/notifications", labelKey: "platformMessages", icon: MessageSquare },
  { href: "/platform/audit", labelKey: "audit", icon: ScrollText },
  { href: "/platform/settings", labelKey: "settings", icon: Settings },
];

export function PlatformShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <RequireArea area="platform">
      <SidebarShell
        title={title}
        items={ITEMS}
        account={<AccountMenu accountHref="/platform/account" />}
      >
        {children}
      </SidebarShell>
    </RequireArea>
  );
}
