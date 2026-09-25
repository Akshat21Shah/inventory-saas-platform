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

import { SidebarShell, type NavItem } from "@/components/shared/app-shell";

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

export function DistributorShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <SidebarShell title={title} items={ITEMS}>
      {children}
    </SidebarShell>
  );
}
