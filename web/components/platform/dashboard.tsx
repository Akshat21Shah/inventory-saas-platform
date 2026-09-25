"use client";

import { Building, CircleCheck, Hourglass, Plus, ShieldOff } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/shared/error-state";
import { KpiCard } from "@/components/shared/kpi-card";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { usePlatformDashboard } from "@/lib/api/generated/endpoints/platform/platform";

export function PlatformDashboard() {
  const t = useTranslations("platform");
  const query = usePlatformDashboard();
  const counts = query.data?.data;
  return (
    <>
      <PageHeader
        title={t("dashboard.title")}
        description={t("dashboard.body")}
        actions={
          <Button asChild className="min-h-10">
            <Link href="/platform/tenants/new">
              <Plus aria-hidden />
              {t("tenants.new")}
            </Link>
          </Button>
        }
      />
      {query.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : counts ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard label={t("dashboard.total")} value={counts.total} icon={Building} />
          <KpiCard label={t("dashboard.active")} value={counts.active} icon={CircleCheck} />
          <KpiCard label={t("dashboard.onboarding")} value={counts.onboarding} icon={Hourglass} />
          <KpiCard label={t("dashboard.suspended")} value={counts.suspended} icon={ShieldOff} />
        </div>
      ) : null}
    </>
  );
}
