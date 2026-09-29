"use client";

import { ClipboardList, House, Search, ShoppingCart, User } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ImpersonationBanner } from "@/components/auth/impersonation-banner";
import { RequireArea } from "@/components/auth/require-area";
import { NotificationBell } from "@/components/notifications/bell";
import { BottomNavShell, type NavItem } from "@/components/shared/app-shell";
import { CartProvider, useCart } from "@/components/shop/cart-state";
import { ShopLiveUpdates } from "@/components/shop/live";

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

function Shell({ title, children }: { title: string; children: ReactNode }) {
  const { count } = useCart();
  return (
    <BottomNavShell
      title={title}
      items={ITEMS}
      banner={<ImpersonationBanner />}
      badges={{ cart: count }}
      headerActions={<NotificationBell scope="shop" tone="onPrimary" />}
    >
      {children}
    </BottomNavShell>
  );
}

export function RetailerShell({ title, children }: { title: string; children: ReactNode }) {
  useServiceWorker();
  const pathname = usePathname();
  const shell = (
    <CartProvider>
      <Shell title={title}>{children}</Shell>
    </CartProvider>
  );
  // The offline page is the service worker's fallback: it must render without a session.
  if (pathname === "/shop/offline") return shell;
  return (
    <RequireArea area="shop">
      <ShopLiveUpdates />
      {shell}
    </RequireArea>
  );
}
