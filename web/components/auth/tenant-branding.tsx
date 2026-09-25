"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { BrandTheme } from "@/components/shared/brand-theme";
import type { PublicBranding } from "@/lib/api/generated/model";
import type { HostKind } from "@/lib/hosts";

interface HostBranding {
  hostKind: HostKind;
  tenantSlug: string | null;
  /** Null on non-tenant hosts or unknown subdomains. */
  branding: PublicBranding | null;
}

interface HostBrandingContextValue extends HostBranding {
  /** Apply freshly saved branding in this tab; the server copy is cached for up to a minute. */
  applyBranding: (changes: Partial<PublicBranding>) => void;
}

const HostBrandingContext = createContext<HostBrandingContextValue>({
  hostKind: "GENERIC",
  tenantSlug: null,
  branding: null,
  applyBranding: () => {},
});

export function HostBrandingProvider({
  value,
  children,
}: {
  value: HostBranding;
  children: ReactNode;
}) {
  const [override, setOverride] = useState<Partial<PublicBranding> | null>(null);
  const context = useMemo<HostBrandingContextValue>(
    () => ({
      ...value,
      branding: value.branding && override ? { ...value.branding, ...override } : value.branding,
      applyBranding: (changes) => setOverride((current) => ({ ...current, ...changes })),
    }),
    [value, override],
  );
  return (
    <HostBrandingContext.Provider value={context}>
      {/* Rendered after the server's theme in <head>, so the same selector wins here. */}
      {override?.primary_color ? <BrandTheme color={override.primary_color} /> : null}
      {children}
    </HostBrandingContext.Provider>
  );
}

export function useHostBranding(): HostBrandingContextValue {
  return useContext(HostBrandingContext);
}
