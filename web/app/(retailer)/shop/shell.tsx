"use client";

import { ClipboardList, House, Search, ShoppingCart, User } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ImpersonationBanner } from "@/components/auth/impersonation-banner";
import { RequireArea } from "@/components/auth/require-area";
import { BottomNavShell, type NavItem } from "@/components/shared/app-shell";

// Bottom navigation per spec §8: Home, Search/Catalog, Cart, Orders, Account.
const ITEMS: NavItem[] = [
  { href: "/shop", labelKey: "home", icon: House },
  { href: "/shop/catalog", labelKey: "catalog", icon: Search },
  { href: "/shop/cart", labelKey: "cart", icon: ShoppingCart },
  { href: "/shop/orders", labelKey: "orders", icon: ClipboardList },
  { href: "/shop/account", labelKey: "account", icon: User },
];

function useServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/shop/sw.js", { scope: "/shop/" }).catch(() => undefined);
  }, []);
}

export function RetailerShell({ title, children }: { title: string; children: ReactNode }) {
  useServiceWorker();
  const pathname = usePathname();
  const shell = (
    <BottomNavShell title={title} items={ITEMS} banner={<ImpersonationBanner />}>
      {children}
    </BottomNavShell>
  );
  // The offline page is the service worker's fallback: it must render without a session.
  return pathname === "/shop/offline" ? shell : <RequireArea area="shop">{shell}</RequireArea>;
}
