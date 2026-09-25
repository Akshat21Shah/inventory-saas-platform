"use client";

import type { LucideIcon } from "lucide-react";
import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  labelKey: string; // key under "nav"
  icon: LucideIcon;
}

function isActive(pathname: string, href: string, rootHref: string) {
  return href === rootHref
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({
  items,
  rootHref,
  onNavigate,
}: {
  items: NavItem[];
  rootHref: string;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const t = useTranslations("nav");
  return (
    <ul className="space-y-1">
      {items.map(({ href, labelKey, icon: Icon }) => {
        const active = isActive(pathname, href, rootHref);
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors",
                active
                  ? "bg-brand-100 text-brand-900"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon aria-hidden className="size-4" />
              {t(labelKey)}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function SkipLink() {
  const t = useTranslations("shell");
  return (
    <a
      href="#main"
      className="bg-background sr-only z-50 rounded-md px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
    >
      {t("skipToContent")}
    </a>
  );
}

/** Desktop-first shell (platform admin, distributor panel): left sidebar, sheet menu on phones. */
export function SidebarShell({
  title,
  items,
  children,
  banner,
  account,
}: {
  title: string;
  items: NavItem[];
  children: ReactNode;
  /** Full-width notice above everything (e.g. a support session). */
  banner?: ReactNode;
  /** Account menu: bottom of the sidebar, top-right on phones. */
  account?: ReactNode;
}) {
  const t = useTranslations();
  const rootHref = items[0]?.href ?? "/";
  return (
    <div className="flex min-h-dvh flex-col">
      {banner}
      <div className="flex min-h-0 flex-1">
        <SkipLink />
        <aside className="bg-sidebar hidden w-60 shrink-0 flex-col border-r md:flex">
          <div className="flex h-14 items-center px-4 font-semibold">{title}</div>
          <nav aria-label={t("nav.mainNavigation")} className="flex-1 px-3 py-2">
            <NavLinks items={items} rootHref={rootHref} />
          </nav>
          {account ? <div className="border-t p-3">{account}</div> : null}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="bg-background/95 sticky top-0 z-30 flex h-14 items-center gap-2 border-b px-4 backdrop-blur md:hidden">
            <Sheet>
              <SheetTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("common.openMenu")}
                  className="size-11"
                >
                  <Menu aria-hidden />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-72 p-4">
                <SheetTitle>{title}</SheetTitle>
                <nav aria-label={t("nav.mainNavigation")} className="mt-4">
                  <NavLinks items={items} rootHref={rootHref} />
                </nav>
              </SheetContent>
            </Sheet>
            <span className="min-w-0 flex-1 truncate font-semibold">{title}</span>
            {account ? <div className="max-w-[50%] min-w-0">{account}</div> : null}
          </header>
          <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

/** Mobile-first retailer shell: bottom navigation with large (≥ 44px) targets, icon + label. */
export function BottomNavShell({
  title,
  items,
  children,
  banner,
}: {
  title: string;
  items: NavItem[];
  children: ReactNode;
  banner?: ReactNode;
}) {
  const pathname = usePathname();
  const t = useTranslations();
  const rootHref = items[0]?.href ?? "/";
  return (
    <div className="flex min-h-dvh flex-col">
      <SkipLink />
      {banner}
      <header className="bg-primary text-primary-foreground sticky top-0 z-30 flex h-14 items-center px-4 font-semibold">
        {title}
      </header>
      <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-4 pt-4 pb-24">
        {children}
      </main>
      <nav
        aria-label={t("nav.mainNavigation")}
        className="bg-background fixed inset-x-0 bottom-0 z-30 border-t pb-[env(safe-area-inset-bottom)]"
      >
        <ul className="mx-auto grid max-w-2xl grid-cols-5">
          {items.map(({ href, labelKey, icon: Icon }) => {
            const active = isActive(pathname, href, rootHref);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium",
                    active ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  <Icon aria-hidden className="size-5" />
                  {t(`nav.${labelKey}`)}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
