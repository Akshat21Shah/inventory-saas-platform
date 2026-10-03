import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { headers } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { cache, type ReactNode } from "react";

import { BrandTheme } from "@/components/shared/brand-theme";
import { fetchPublicBranding } from "@/lib/branding";
import type { HostKind } from "@/lib/hosts";
import { languageOf } from "@/lib/i18n/config";
import { getTranslations } from "@/lib/i18n/server";

import { Providers } from "./providers";
import "./globals.css";
import "./fonts.css";

const inter = Inter({ variable: "--font-sans", subsets: ["latin"], display: "swap" });

/** Host classification (set by proxy.ts) and, on a tenant subdomain, its public branding. */
const hostContext = cache(async () => {
  const h = await headers();
  const hostKind = (h.get("x-host-kind") ?? "GENERIC") as HostKind;
  const tenantSlug = h.get("x-tenant-slug");
  const branding =
    hostKind === "TENANT" && tenantSlug ? await fetchPublicBranding(tenantSlug) : null;
  return { hostKind, tenantSlug, branding };
});

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  const { branding } = await hostContext();
  const name = branding?.display_name || t("name");
  return {
    title: { default: name, template: `%s · ${name}` },
    description: t("tagline"),
    ...(branding?.favicon_url ? { icons: { icon: branding.favicon_url } } : {}),
  };
}

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#ffffff" };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const host = await hostContext();
  return (
    // Browsers and extensions add attributes to <html> and <body> before React loads (Chrome's
    // __gcrremoteframetoken, translators, password managers). Ignore attribute differences on these
    // two tags only; mismatches anywhere inside the page are still reported.
    <html
      lang={languageOf(locale)}
      className={`${inter.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Tenant colour as CSS variables before first paint (ADR-028: derived on the client). */}
        <BrandTheme color={host.branding?.primary_color} />
      </head>
      <body className="bg-background text-foreground min-h-full font-sans" suppressHydrationWarning>
        <NextIntlClientProvider>
          <Providers host={host}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
