"use client";

import { LogOut, ShieldAlert } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, type ReactNode } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { homeFor } from "@/lib/auth/urls";

import { useAuth } from "./auth-provider";

export type Area = "platform" | "manage" | "shop";

const USER_TYPE: Record<Area, string> = { platform: "PLATFORM", manage: "STAFF", shop: "RETAILER" };
const LOGIN_PATH: Record<Area, string> = {
  platform: "/login",
  manage: "/login",
  shop: "/shop/login",
};

/**
 * Client-side guard for an area (cosmetic: the API enforces everything). Anonymous visitors go to
 * the right sign-in page; other account types see a short explanation.
 */
export function RequireArea({ area, children }: { area: Area; children: ReactNode }) {
  const { status, me, blockedCode, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("auth");

  useEffect(() => {
    if (status === "anonymous" && blockedCode !== "TENANT_UNAVAILABLE") {
      router.replace(`${LOGIN_PATH[area]}?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, blockedCode, area, pathname, router]);

  if (status === "loading" || (status === "anonymous" && blockedCode !== "TENANT_UNAVAILABLE")) {
    return <PageSkeleton />;
  }
  if (status === "anonymous") {
    return (
      <EmptyState
        icon={ShieldAlert}
        title={t("unavailableTitle")}
        description={t("unavailableBody")}
      />
    );
  }
  if (me && me.user_type !== USER_TYPE[area]) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title={t("wrongAreaTitle")}
        description={t("wrongAreaBody")}
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <Button onClick={() => router.push(homeFor(me.user_type))} className="min-h-11">
              {t("goToMyArea")}
            </Button>
            <Button variant="outline" onClick={() => void signOut()} className="min-h-11">
              <LogOut aria-hidden />
              {t("signOut")}
            </Button>
          </div>
        }
      />
    );
  }
  return <>{children}</>;
}
