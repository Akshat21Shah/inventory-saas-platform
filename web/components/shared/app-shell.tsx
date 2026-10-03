"use client";

import type { LucideIcon } from "lucide-react";
import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  labelKey: string; // key under "nav"
  icon: LucideIcon;
  /** Shown only with this permission (cosmetic: the server guards every page). */
  permission?: string;
  /** Shown only while this optional module is on. */
  feature?: string;
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
  badges,
}: {
  items: NavItem[];
  rootHref: string;
  onNavigate?: () => void;
  badges?: Partial<Record<string, number>>;
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
              <span className="flex-1">{t(labelKey)}</span>
              {badges?.[labelKey] ? (
                <span className="bg-warning/20 text-warning-strong rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums">
                  {badges[labelKey]}
                  <span className="sr-only"> {t("needsAttention")}</span>
                </span>
              ) : null}
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
  badges,
  headerActions,
  search,
  searchIcon,
}: {
  title: string;
  items: NavItem[];
  children: ReactNode;
  /** Global search: a field above the navigation on laptops… */
  search?: ReactNode;
  /** …and an icon in the header on phones. */
  searchIcon?: ReactNode;
  /** Counts shown next to nav items, by label key (e.g. open stock alerts). */
  badges?: Partial<Record<string, number>>;
  /** Next to the title (e.g. the notification bell): sidebar top on laptops, header on phones. */
  headerActions?: ReactNode;
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
          <div className="flex h-14 items-center gap-2 px-4">
            <span className="min-w-0 flex-1 truncate font-semibold">{title}</span>
            {headerActions}
          </div>
          {search ? <div className="px-3 pt-1">{search}</div> : null}
          <nav aria-label={t("nav.mainNavigation")} className="flex-1 px-3 py-2">
            <NavLinks items={items} rootHref={rootHref} badges={badges} />
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
                  <NavLinks items={items} rootHref={rootHref} badges={badges} />
                </nav>
              </SheetContent>
            </Sheet>
            <span className="min-w-0 flex-1 truncate font-semibold">{title}</span>
            {searchIcon}
            {headerActions}
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
/** A count on a nav icon (e.g. items in the cart); the label is read out with it. */
function CountBadge({ count, label }: { count?: number; label: string }) {
  if (!count) return null;
  return (
    <span
      aria-label={label}
      className="bg-destructive text-destructive-foreground absolute -top-1.5 -right-2.5 min-w-5 rounded-full px-1 text-center text-[11px] leading-5 font-semibold tabular-nums"
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

export function BottomNavShell({
  title,
  items,
  children,
  banner,
  badges,
  headerActions,
}: {
  title: string;
  items: NavItem[];
  children: ReactNode;
  banner?: ReactNode;
  /** Counts on nav icons, by label key (e.g. the cart's item count). */
  badges?: Partial<Record<string, number>>;
  /** At the right end of the header (e.g. the notification bell). */
  headerActions?: ReactNode;
}) {
  const pathname = usePathname();
  const t = useTranslations();
  const rootHref = items[0]?.href ?? "/";
  return (
    <div className="flex min-h-dvh flex-col">
      <SkipLink />
      {banner}
      <header className="bg-primary text-primary-foreground sticky top-0 z-30 h-14">
        <div className="mx-auto flex h-full w-full max-w-6xl items-center justify-between gap-4 px-4">
          <span className="min-w-0 truncate font-semibold">{title}</span>
          {/* Wide screens: the same links in the header instead of the phone's bottom bar. */}
          <nav aria-label={t("nav.mainNavigation")} className="hidden lg:block">
            <ul className="flex gap-1">
              {items.map(({ href, labelKey, icon: Icon }) => {
                const active = isActive(pathname, href, rootHref);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-10 items-center gap-2 rounded-full px-4 text-sm font-medium",
                        active
                          ? "bg-primary-foreground text-primary"
                          : "text-primary-foreground/90 hover:bg-primary-foreground/15",
                      )}
                    >
                      <span className="relative">
                        <Icon aria-hidden className="size-4" />
                        <CountBadge
                          count={badges?.[labelKey]}
                          label={t("nav.itemCount", { count: badges?.[labelKey] ?? 0 })}
                        />
                      </span>
                      {t(`nav.${labelKey}`)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          {headerActions ? <div className="flex shrink-0 items-center">{headerActions}</div> : null}
        </div>
      </header>
      {/* Phones keep one comfortable column; tablets and laptops use the room they have. */}
      <main
        id="main"
        className="mx-auto w-full max-w-2xl flex-1 px-4 pt-4 pb-24 md:max-w-4xl lg:max-w-6xl lg:pb-10"
      >
        {children}
      </main>
      <nav
        aria-label={t("nav.mainNavigation")}
        className="bg-background fixed inset-x-0 bottom-0 z-30 border-t pb-[env(safe-area-inset-bottom)] lg:hidden"
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
                  <span className="relative">
                    <Icon aria-hidden className="size-5" />
                    <CountBadge
                      count={badges?.[labelKey]}
                      label={t("nav.itemCount", { count: badges?.[labelKey] ?? 0 })}
                    />
                  </span>
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
