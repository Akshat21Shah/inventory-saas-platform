"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { PublicBranding } from "@/lib/api/generated/model";
import type { HostKind } from "@/lib/hosts";

interface HostBranding {
  hostKind: HostKind;
  tenantSlug: string | null;
  /** Null on non-tenant hosts or unknown subdomains. */
  branding: PublicBranding | null;
}

const HostBrandingContext = createContext<HostBranding>({
  hostKind: "GENERIC",
  tenantSlug: null,
  branding: null,
});

export function HostBrandingProvider({
  value,
  children,
}: {
  value: HostBranding;
  children: ReactNode;
}) {
  return <HostBrandingContext.Provider value={value}>{children}</HostBrandingContext.Provider>;
}

export function useHostBranding(): HostBranding {
  return useContext(HostBrandingContext);
}
