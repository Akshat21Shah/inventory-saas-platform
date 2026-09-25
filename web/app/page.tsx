import { Building, LayoutDashboard, Palette, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { headers } from "next/headers";

import type { HostKind } from "@/lib/hosts";

/** Host-aware landing. Phase 1 redirects signed-in users straight to their area. */
export default async function LandingPage() {
  const t = await getTranslations();
  const hostKind = ((await headers()).get("x-host-kind") ?? "GENERIC") as HostKind;
  const links = [
    {
      href: "/shop",
      icon: ShoppingCart,
      title: t("landing.retailer"),
      hint: t("landing.retailerHint"),
      show: hostKind !== "ADMIN",
    },
    {
      href: "/manage",
      icon: LayoutDashboard,
      title: t("landing.distributor"),
      hint: t("landing.distributorHint"),
      show: hostKind !== "ADMIN",
    },
    {
      href: "/platform",
      icon: Building,
      title: t("landing.platform"),
      hint: t("landing.platformHint"),
      show: hostKind === "ADMIN" || process.env.NODE_ENV !== "production",
    },
    {
      href: "/design-system",
      icon: Palette,
      title: t("landing.designSystem"),
      hint: "",
      show: process.env.NODE_ENV !== "production",
    },
  ].filter((link) => link.show);

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-8 px-4 py-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">{t("app.name")}</h1>
        <p className="text-muted-foreground">{t("app.tagline")}</p>
      </header>
      <ul className="grid gap-3">
        {links.map(({ href, icon: Icon, title, hint }) => (
          <li key={href}>
            <Link
              href={href}
              className="hover:border-brand-400 hover:bg-brand-50 flex min-h-16 items-center gap-4 rounded-xl border p-4 transition-colors"
            >
              <Icon aria-hidden className="text-primary size-6" />
              <span>
                <span className="block font-medium">{title}</span>
                {hint ? <span className="text-muted-foreground block text-sm">{hint}</span> : null}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
