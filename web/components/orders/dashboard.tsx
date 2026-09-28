"use client";

import { ClipboardList, PackageCheck, PackageSearch, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAuth } from "@/components/auth/auth-provider";
import { KpiCard } from "@/components/shared/kpi-card";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { useOrdersCounts } from "@/lib/api/generated/endpoints/orders/orders";

/** The distributor opens on what needs action today (spec §8). */
export function DistributorDashboard() {
  const t = useTranslations("orders.dashboard");
  const { can } = useAuth();
  const counts = useOrdersCounts({ query: { enabled: can("orders.view") } });
  const c = counts.data?.data;
  const cards = [
    { href: "/manage/orders", label: t("new"), value: c?.new, icon: ClipboardList },
    { href: "/manage/orders", label: t("onHold"), value: c?.on_hold, icon: ShieldAlert },
    {
      href: "/manage/backorders",
      label: t("proposals"),
      value: c?.proposals,
      icon: PackageSearch,
    },
    {
      href: "/manage/orders/shipments",
      label: t("toPack"),
      value: c?.to_pack,
      icon: PackageCheck,
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      {!can("orders.view") ? null : counts.isLoading ? (
        <CardSkeleton />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {cards.map((card) => (
            <li key={card.label}>
              <Link href={card.href} className="block rounded-xl focus-visible:ring-2">
                <KpiCard label={card.label} value={card.value ?? 0} icon={card.icon} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
