"use client";

import { Store } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { useHostBranding } from "./tenant-branding";

/** Branded sign-in frame: the distributor's logo and name on its subdomain, else the platform's. */
export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const t = useTranslations();
  const { branding } = useHostBranding();
  const name = branding?.display_name || t("app.name");
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 px-4 py-10">
      <div className="flex items-center gap-3">
        {branding?.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- presigned redirect, not a static asset
          <img src={branding.logo_url} alt="" className="size-10 rounded-lg object-contain" />
        ) : (
          <span className="bg-primary text-primary-foreground flex size-10 items-center justify-center rounded-lg">
            <Store aria-hidden className="size-5" />
          </span>
        )}
        <span className="text-lg font-semibold">{name}</span>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{title}</h1>
          </CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent className="space-y-4">{children}</CardContent>
      </Card>
      {footer ? <div className="text-muted-foreground text-center text-sm">{footer}</div> : null}
    </main>
  );
}

/** Shown instead of any sign-in form while the tenant is not available (ADR-032). */
export function UnavailableCard() {
  const t = useTranslations("auth");
  return (
    <AuthCard title={t("unavailableTitle")}>
      <p role="status" className="text-muted-foreground">
        {t("unavailableBody")}
      </p>
    </AuthCard>
  );
}
