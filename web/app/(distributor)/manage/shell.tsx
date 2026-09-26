"use client";

import {
  Boxes,
  ChartColumn,
  ClipboardList,
  FileText,
  LayoutDashboard,
  Package,
  PackageSearch,
  Percent,
  Settings,
  Users,
  Wallet,
} from "lucide-react";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/auth/account-menu";
import { useAuth } from "@/components/auth/auth-provider";
import { ImpersonationBanner } from "@/components/auth/impersonation-banner";
import { RequireArea } from "@/components/auth/require-area";
import { SidebarShell, type NavItem } from "@/components/shared/app-shell";
import { useStockSummary } from "@/lib/api/generated/endpoints/inventory/inventory";

const ITEMS: NavItem[] = [
  { href: "/manage", labelKey: "dashboard", icon: LayoutDashboard },
  { href: "/manage/orders", labelKey: "orders", icon: ClipboardList },
  { href: "/manage/backorders", labelKey: "backorders", icon: PackageSearch },
  { href: "/manage/products", labelKey: "products", icon: Package },
  { href: "/manage/retailers", labelKey: "retailers", icon: Users },
  { href: "/manage/pricing/price-lists", labelKey: "pricing", icon: Percent },
  { href: "/manage/stock", labelKey: "stock", icon: Boxes },
  { href: "/manage/invoices", labelKey: "invoices", icon: FileText },
  { href: "/manage/payments", labelKey: "payments", icon: Wallet },
  { href: "/manage/reports", labelKey: "reports", icon: ChartColumn },
  { href: "/manage/settings/business", labelKey: "settings", icon: Settings },
];

/** Open stock alerts next to "Stock" (refreshed every minute). */
function useNavBadges(): Partial<Record<string, number>> {
  const { me, can } = useAuth();
  const summary = useStockSummary({
    query: { enabled: Boolean(me) && can("stock.view"), refetchInterval: 60_000 },
  });
  const alerts = summary.data?.data.alerts ?? {};
  return { stock: Object.values(alerts).reduce((total, n) => total + n, 0) };
}

function Shell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <SidebarShell
      title={title}
      items={ITEMS}
      badges={useNavBadges()}
      banner={<ImpersonationBanner />}
      account={<AccountMenu accountHref="/manage/account" />}
    >
      {children}
    </SidebarShell>
  );
}

export function DistributorShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <RequireArea area="manage">
      <Shell title={title}>{children}</Shell>
    </RequireArea>
  );
}
