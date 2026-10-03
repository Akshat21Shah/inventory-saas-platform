"use client";

import Link from "next/link";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { MoneyText } from "@/components/shared/money-text";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { usePlatformAiUsage } from "@/lib/api/generated/endpoints/platform/platform";
import { useSettingsAiUsage } from "@/lib/api/generated/endpoints/settings/settings";
import type { TenantAiUsage } from "@/lib/api/generated/model";
import { formatDate, formatMoney, formatQty } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";

const count = (n: number) => formatQty(String(n), 0);

/** "Claude Sonnet 5.5" for the model id (the id itself when unknown). */
function useModelName() {
  const t = useTranslations("aiModels");
  return (model: string) => (t.has(model) ? t(model) : model);
}

/** This business's AI use this month in estimated rupees, questions and searches, against the
 * monthly allowance (ADR-059 item 8), on the features page while the AI module is on. The
 * provider's units stay behind the scenes. */
export function AiUsageCard() {
  const t = useTranslations("distributorSettings.features.aiUsage");
  const modelName = useModelName();
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
          <CardContent className="space-y-4 py-4">
            <p className="text-muted-foreground text-sm">
              {t("body", { since: formatDate(data.since), model: modelName(data.model) })}
            </p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <p className="text-2xl font-semibold tabular-nums">
                {data.allowance
                  ? t("costOfLimit", {
                      cost: formatMoney(data.cost),
                      limit: formatMoney(data.allowance.cost),
                    })
                  : formatMoney(data.cost)}
              </p>
              {data.near_limit ? <StatusBadge status="NEAR_LIMIT" labels="usageStatus" /> : null}
            </div>
            <dl className="grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="font-medium">{t("used")}</dt>
                <dd className="text-muted-foreground">
                  {t("usedQuestions", { count: data.questions })}
                </dd>
                <dd className="text-muted-foreground">
                  {t("usedSearches", { count: data.searches })}
                </dd>
              </div>
              <div>
                <dt className="font-medium">{t("allowance")}</dt>
                {data.allowance ? (
                  <>
                    <dd className="text-muted-foreground">
                      {t("allowanceQuestions", { count: count(data.allowance.questions) })}
                    </dd>
                    <dd className="text-muted-foreground">
                      {t("allowanceSearches", { count: count(data.allowance.searches) })}
                    </dd>
                  </>
                ) : (
                  <dd className="text-muted-foreground">{t("noLimit")}</dd>
                )}
              </div>
            </dl>
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
                      {formatMoney(row.cost)} · {t("calls", { calls: row.calls })}
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

/** Each distributor's AI use this month in estimated rupees, questions and searches, the
 * dearest first, and what the monthly cap comes to, on the super admin's dashboard. */
export function PlatformAiUsage() {
  const t = useTranslations("platform.dashboard.ai");
  const modelName = useModelName();
  const query = usePlatformAiUsage();
  const data = query.data?.data;
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
      id: "cost",
      header: t("cost"),
      cell: ({ row }) =>
        data?.allowance ? (
          <span className="tabular-nums">
            {t("costOfLimit", {
              cost: formatMoney(row.original.cost),
              limit: formatMoney(data.allowance.cost),
            })}
          </span>
        ) : (
          <MoneyText value={row.original.cost} />
        ),
    },
    {
      id: "questions",
      header: t("questions"),
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.questions)}</span>,
    },
    {
      id: "searches",
      header: t("searches"),
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.searches)}</span>,
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
    {
      id: "units",
      header: t("units"),
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.units)}</span>,
    },
  ];
  return (
    <section aria-labelledby="platform-ai" className="space-y-3">
      <div className="space-y-1">
        <h2 id="platform-ai" className="text-lg font-semibold">
          {t("title")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("body")}</p>
        {data ? (
          <p className="text-sm">
            {data.allowance
              ? t("allowance", {
                  questions: count(data.allowance.questions),
                  searches: count(data.allowance.searches),
                  cost: formatMoney(data.allowance.cost),
                  model: modelName(data.model),
                })
              : t("noLimit", { model: modelName(data.model) })}
          </p>
        ) : null}
      </div>
      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          data={data?.rows ?? []}
          isLoading={query.isLoading}
          getRowId={(row) => row.tenant_id}
          numericColumns={["cost", "questions", "searches", "failed", "units"]}
          caption={t("title")}
          empty={{ title: t("empty") }}
          cardLayout={{
            name: "title",
            cost: "primary",
            questions: "primary",
            searches: "primary",
            near: "primary",
            failed: "secondary",
            units: "secondary",
          }}
        />
      )}
    </section>
  );
}
