"use client";

import { Activity, Building, CircleCheck, Hourglass, Plus, ShieldOff } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { DailyChart } from "@/components/dashboard/daily-chart";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { KpiCard } from "@/components/shared/kpi-card";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { usePlatformDashboard } from "@/lib/api/generated/endpoints/platform/platform";
import type { Dashboard, PlanUsage, TenantFailures, TopTenant } from "@/lib/api/generated/model";
import { formatMoney } from "@/lib/format";

function TenantLink({ id, name }: { id: string; name: string }) {
  return (
    <Link
      href={`/platform/tenants/${id}`}
      className="text-primary font-medium underline-offset-4 hover:underline"
    >
      {name}
    </Link>
  );
}

/** "12 of 50", or just the count when the plan has no limit. */
function Used({ used, limit }: { used: number; limit: number | null }) {
  const t = useTranslations("platform.dashboard.usage");
  return (
    <span className="tabular-nums">{limit === null ? used : t("ofLimit", { used, limit })}</span>
  );
}

function Section({
  id,
  title,
  body,
  children,
}: {
  id: string;
  title: string;
  body?: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div>
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        {body ? <p className="text-muted-foreground text-sm">{body}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** How many distributors the usage list shows before "Show all": those near a limit always. */
const USAGE_SHOWN = 10;

function Health({ data }: { data: Dashboard }) {
  const t = useTranslations("platform.dashboard");
  const [allUsage, setAllUsage] = useState(false);
  const errors = data.errors_24h;
  // Near a limit first (the server's order), then the first few others.
  const usage = allUsage
    ? data.usage
    : data.usage.filter((row, index) => row.near_limit || index < USAGE_SHOWN);
  const topColumns: DataTableColumn<TopTenant>[] = [
    {
      id: "name",
      header: t("top.name"),
      cell: ({ row }) => <TenantLink id={row.original.tenant_id} name={row.original.name} />,
    },
    {
      id: "orders",
      header: t("top.orders"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.orders}</span>,
    },
    {
      id: "value",
      header: t("top.value"),
      cell: ({ row }) => <MoneyText value={row.original.value} />,
    },
  ];
  const failureColumns: DataTableColumn<TenantFailures>[] = [
    {
      id: "name",
      header: t("failures.name"),
      cell: ({ row }) => <TenantLink id={row.original.tenant_id} name={row.original.name} />,
    },
    {
      id: "messages",
      header: t("failures.messages"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.failed_messages}</span>,
    },
    {
      id: "irns",
      header: t("failures.irns"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.failed_irns}</span>,
    },
    {
      id: "ewaybills",
      header: t("failures.ewaybills"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.failed_ewaybills}</span>,
    },
    {
      id: "connections",
      header: t("failures.connections"),
      cell: ({ row }) => {
        const broken = [
          row.original.gst_login_failed ? t("failures.gstLogin") : null,
          row.original.gateway_failed ? t("failures.gateway") : null,
        ].filter((x): x is string => x !== null);
        return broken.length ? (
          <span className="flex flex-wrap gap-1">
            {broken.map((label) => (
              <span
                key={label}
                className="bg-destructive/10 text-destructive ring-destructive/30 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset"
              >
                {label}
              </span>
            ))}
          </span>
        ) : (
          "—"
        );
      },
    },
  ];
  const usageColumns: DataTableColumn<PlanUsage>[] = [
    {
      id: "name",
      header: t("usage.name"),
      cell: ({ row }) => <TenantLink id={row.original.tenant_id} name={row.original.name} />,
    },
    { id: "plan", header: t("usage.plan"), cell: ({ row }) => row.original.plan || "—" },
    {
      id: "shops",
      header: t("usage.shops"),
      cell: ({ row }) => <Used used={row.original.shops} limit={row.original.max_shops} />,
    },
    {
      id: "staff",
      header: t("usage.staff"),
      cell: ({ row }) => <Used used={row.original.staff} limit={row.original.max_staff} />,
    },
    {
      id: "products",
      header: t("usage.products"),
      cell: ({ row }) => <Used used={row.original.products} limit={row.original.max_products} />,
    },
    {
      id: "near",
      header: t("usage.near"),
      cell: ({ row }) =>
        row.original.near_limit ? <StatusBadge status="NEAR_LIMIT" labels="usageStatus" /> : "—",
    },
  ];
  return (
    <div className="space-y-8">
      <Section id="platform-orders" title={t("orders.title")} body={t("orders.body")}>
        <Card>
          <CardContent className="py-4">
            <DailyChart
              rows={data.orders_per_day}
              caption={t("orders.caption")}
              dateLabel={t("orders.date")}
              series={[
                {
                  key: "value",
                  label: t("orders.value"),
                  color: "var(--primary)",
                  format: (value) => formatMoney(value),
                },
              ]}
            />
          </CardContent>
        </Card>
      </Section>
      <div className="grid gap-8 xl:grid-cols-2">
        <Section id="platform-top" title={t("top.title")} body={t("top.body")}>
          <DataTable
            columns={topColumns}
            data={data.top_tenants}
            getRowId={(row) => row.tenant_id}
            numericColumns={["orders", "value"]}
            caption={t("top.title")}
            empty={{ title: t("top.empty") }}
            cardLayout={{ name: "title", orders: "primary", value: "primary" }}
          />
        </Section>
        <Section id="platform-errors" title={t("errors.title")} body={t("errors.body")}>
          <Card>
            <CardContent className="flex items-center gap-4 py-5">
              <span className="bg-brand-50 text-primary flex size-10 items-center justify-center rounded-lg">
                <Activity aria-hidden className="size-5" />
              </span>
              <div>
                <p className="text-2xl font-semibold tabular-nums">
                  {errors.rate === null ? "—" : `${errors.rate}%`}
                </p>
                <p className="text-muted-foreground text-sm">
                  {t("errors.detail", {
                    errors: errors.server_errors,
                    requests: errors.requests,
                  })}
                </p>
              </div>
            </CardContent>
          </Card>
        </Section>
      </div>
      <Section id="platform-failures" title={t("failures.title")} body={t("failures.body")}>
        <DataTable
          columns={failureColumns}
          data={data.failures}
          getRowId={(row) => row.tenant_id}
          numericColumns={["messages", "irns", "ewaybills"]}
          caption={t("failures.title")}
          empty={{ title: t("failures.empty"), description: t("failures.emptyBody") }}
          cardLayout={{
            name: "title",
            messages: "primary",
            irns: "primary",
            ewaybills: "primary",
            connections: "primary",
          }}
        />
      </Section>
      <Section id="platform-usage" title={t("usage.title")} body={t("usage.body")}>
        <DataTable
          columns={usageColumns}
          data={usage}
          getRowId={(row) => row.tenant_id}
          caption={t("usage.title")}
          empty={{ title: t("usage.empty") }}
          cardLayout={{
            name: "title",
            near: "primary",
            shops: "primary",
            staff: "primary",
            products: "primary",
            plan: "secondary",
          }}
        />
        {usage.length < data.usage.length ? (
          <Button variant="outline" className="min-h-11" onClick={() => setAllUsage(true)}>
            {t("usage.showAll", { count: data.usage.length })}
          </Button>
        ) : null}
      </Section>
    </div>
  );
}

/** The super admin's view of the platform (ADR-050 item 12): distributors, orders across them,
 * what is failing where, usage against plans and the error rate. */
export function PlatformDashboard() {
  const t = useTranslations("platform");
  const query = usePlatformDashboard({ query: { refetchInterval: 60_000 } });
  const data = query.data?.data;
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
      ) : query.error || !data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard label={t("dashboard.total")} value={data.total} icon={Building} />
            <KpiCard label={t("dashboard.active")} value={data.active} icon={CircleCheck} />
            <KpiCard label={t("dashboard.onboarding")} value={data.onboarding} icon={Hourglass} />
            <KpiCard label={t("dashboard.suspended")} value={data.suspended} icon={ShieldOff} />
          </div>
          <Health data={data} />
        </div>
      )}
    </>
  );
}
