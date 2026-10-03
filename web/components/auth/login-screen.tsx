"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { homeFor } from "@/lib/auth/urls";

import { AuthCard, UnavailableCard } from "./auth-card";
import { useAuth } from "./auth-provider";
import { RetailerSignIn } from "./retailer-sign-in";
import { StaffSignIn } from "./staff-sign-in";
import { useHostBranding } from "./tenant-branding";

/**
 * The session state when the page was opened. Only visitors who arrive already signed in are sent
 * on; a sign-in completed on this page keeps its flow on screen (e.g. recovery codes after 2FA
 * set-up are shown once and must not be skipped by an automatic redirect).
 */
function useArrivalStatus() {
  const { status, me } = useAuth();
  const [arrival, setArrival] = useState<"loading" | "signedIn" | "signedOut">("loading");
  // Adjusting state while rendering (react.dev "storing information from previous renders").
  if (arrival === "loading" && status !== "loading") {
    setArrival(status === "authenticated" ? "signedIn" : "signedOut");
  }
  return { arrival, me };
}

/** /login adapts to the host (ADR-020): admin host → super admin; tenant subdomain → staff (with a
 * link for shop owners); generic domain → a choice between shop owner and staff. */
export function LoginScreen() {
  const t = useTranslations("auth");
  const { hostKind, branding } = useHostBranding();
  const { arrival, me } = useArrivalStatus();
  const router = useRouter();

  useEffect(() => {
    if (arrival === "signedIn" && me) router.replace(homeFor(me.user_type));
  }, [arrival, me, router]);

  if (arrival !== "signedOut") return <PageSkeleton />;

  if (hostKind === "ADMIN") {
    return (
      <AuthCard title={t("platformSignInTitle")} description={t("platformSignInBody")}>
        <StaffSignIn />
      </AuthCard>
    );
  }
  if (hostKind === "TENANT") {
    if (!branding?.available) return <UnavailableCard />;
    return (
      <AuthCard
        title={t("staffSignInTitle")}
        description={t("staffSignInBody")}
        footer={
          <Link href="/shop/login" className="text-primary underline-offset-4 hover:underline">
            {t("shopOwnerLink")}
          </Link>
        }
      >
        <StaffSignIn />
      </AuthCard>
    );
  }
  return (
    <AuthCard title={t("signInTitle")}>
      <Tabs defaultValue="retailer">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="retailer" className="min-h-10">
            {t("tabRetailer")}
          </TabsTrigger>
          <TabsTrigger value="staff" className="min-h-10">
            {t("tabStaff")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="retailer" className="pt-4">
          <RetailerSignIn />
        </TabsContent>
        <TabsContent value="staff" className="pt-4">
          <StaffSignIn />
        </TabsContent>
      </Tabs>
    </AuthCard>
  );
}

/** /shop/login on a distributor's subdomain: mobile number + code. */
export function ShopLoginScreen() {
  const t = useTranslations("auth");
  const { hostKind, branding } = useHostBranding();
  const { arrival, me } = useArrivalStatus();
  const router = useRouter();

  useEffect(() => {
    if (arrival === "signedIn" && me) router.replace(homeFor(me.user_type));
    if (hostKind !== "TENANT") router.replace("/login");
  }, [arrival, me, router, hostKind]);

  if (arrival !== "signedOut" || hostKind !== "TENANT") return <PageSkeleton />;
  if (!branding?.available) return <UnavailableCard />;
  return (
    <AuthCard title={t("retailer.title")} description={t("retailer.body")} shopDefault>
      <RetailerSignIn />
    </AuthCard>
  );
}
