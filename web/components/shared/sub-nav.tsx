"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth/auth-provider";
import { cn } from "@/lib/utils";

export interface SubNavItem {
  href: string;
  label: string;
  /** Hidden unless the user has this permission (cosmetic; the server enforces it). */
  permission?: string;
  /** Also active on deeper paths (e.g. a list and its detail pages). */
  prefix?: boolean;
  /** Custom "is this the current section" test, when prefixes overlap. */
  match?: (pathname: string) => boolean;
}

/** A row of section tabs under a page (scrolls sideways on phones). */
export function SubNav({ items, label }: { items: SubNavItem[]; label: string }) {
  const pathname = usePathname();
  const { can } = useAuth();
  return (
    <nav aria-label={label} className="-mx-4 mb-6 overflow-x-auto px-4">
      <ul className="flex gap-2">
        {items
          .filter((item) => !item.permission || can(item.permission))
          .map((item) => {
            const active = item.match
              ? item.match(pathname)
              : pathname === item.href || (item.prefix && pathname.startsWith(`${item.href}/`));
            return (
              <li key={item.href} className="shrink-0">
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-10 items-center rounded-full border px-4 text-sm whitespace-nowrap",
                    active
                      ? "bg-brand-50 text-brand-900 border-brand-200 font-medium"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
      </ul>
    </nav>
  );
}
