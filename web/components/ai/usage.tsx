"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { usePlatformAiUsage } from "@/lib/api/generated/endpoints/platform/platform";
import { useSettingsAiUsage } from "@/lib/api/generated/endpoints/settings/settings";
import type { TenantAiUsage } from "@/lib/api/generated/model";
import { formatDate, formatQty } from "@/lib/format";

const count = (n: number) => formatQty(String(n), 0);

/** This business's AI use this month against the monthly limit (ADR-058), on the features page
 * while the AI module is on. */
export function AiUsageCard() {
  const t = useTranslations("distributorSettings.features.aiUsage");
  const query = useSettingsAiUsage();
  const data = query.data?.data;
  return (
    <section aria-labelledby="ai-usage" className="space-y-3">
      <h2 id="ai-usage" className="text-lg font-semibold">
        {t("title")}
      </h2>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error || !data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <Card>
          <CardContent className="space-y-3 py-4">
            <p className="text-muted-foreground text-sm">
              {t("body", { since: formatDate(data.since) })}
            </p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <p className="text-2xl font-semibold tabular-nums">
                {data.limit === null
                  ? t("units", { units: count(data.units) })
                  : t("ofLimit", { units: count(data.units), limit: count(data.limit) })}
              </p>
              {data.near_limit ? <StatusBadge status="NEAR_LIMIT" labels="usageStatus" /> : null}
            </div>
            {data.limit === null ? (
              <p className="text-muted-foreground text-sm">{t("noLimit")}</p>
            ) : null}
            {data.by_feature.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("none")}</p>
            ) : (
              <ul className="divide-y text-sm">
                {data.by_feature.map((row) => (
                  <li
                    key={row.feature}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2"
                  >
                    <span>{t(`feature.${row.feature}`)}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {t("units", { units: count(row.units) })} · {t("calls", { calls: row.calls })}
                      {row.failed ? ` · ${t("failed", { failed: row.failed })}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}

/** Each distributor's AI use this month, the heaviest first, on the super admin's dashboard. */
export function PlatformAiUsage() {
  const t = useTranslations("platform.dashboard.ai");
  const query = usePlatformAiUsage();
  const columns: DataTableColumn<TenantAiUsage>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/platform/tenants/${row.original.tenant_id}`}
          className="text-primary font-medium underline-offset-4 hover:underline"
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      id: "units",
      header: t("units"),
      cell: ({ row }) => (
        <span className="tabular-nums">
          {row.original.limit === null
            ? count(row.original.units)
            : t("ofLimit", {
                used: count(row.original.units),
                limit: count(row.original.limit),
              })}
        </span>
      ),
    },
    {
      id: "calls",
      header: t("calls"),
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.calls)}</span>,
    },
    {
      id: "failed",
      header: t("failed"),
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.failed)}</span>,
    },
    {
      id: "near",
      header: t("near"),
      cell: ({ row }) =>
        row.original.near_limit ? <StatusBadge status="NEAR_LIMIT" labels="usageStatus" /> : "—",
    },
  ];
  return (
    <section aria-labelledby="platform-ai" className="space-y-3">
      <div>
        <h2 id="platform-ai" className="text-lg font-semibold">
          {t("title")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("body")}</p>
      </div>
      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          data={query.data?.data ?? []}
          isLoading={query.isLoading}
          getRowId={(row) => row.tenant_id}
          numericColumns={["units", "calls", "failed"]}
          caption={t("title")}
          empty={{ title: t("empty") }}
          cardLayout={{
            name: "title",
            units: "primary",
            calls: "primary",
            failed: "primary",
            near: "primary",
          }}
        />
      )}
    </section>
  );
}
