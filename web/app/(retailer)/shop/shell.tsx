"use client";

import { ClipboardList, House, Search, ShoppingCart, User } from "lucide-react";
import { useEffect, type ReactNode } from "react";

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
  return (
    <BottomNavShell title={title} items={ITEMS}>
      {children}
    </BottomNavShell>
  );
}
