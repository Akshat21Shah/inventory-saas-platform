"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthProvider } from "@/components/auth/auth-provider";
import { HostBrandingProvider } from "@/components/auth/tenant-branding";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { PublicBranding } from "@/lib/api/generated/model";
import type { HostKind } from "@/lib/hosts";
import { makeQueryClient } from "@/lib/query-client";

interface HostValue {
  hostKind: HostKind;
  tenantSlug: string | null;
  branding: PublicBranding | null;
}

export function Providers({ host, children }: { host: HostValue; children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <HostBrandingProvider value={host}>
        <AuthProvider>
          <TooltipProvider>
            {children}
            <Toaster richColors position="top-center" />
          </TooltipProvider>
        </AuthProvider>
      </HostBrandingProvider>
    </QueryClientProvider>
  );
}
