"use client";

import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  FileWarning,
  Info,
  PackageCheck,
  PackageSearch,
  ShieldAlert,
  ShoppingCart,
  Truck,
  UserX,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { ComplianceCards, FailedEWayBillsAlert } from "@/components/compliance/dashboard";
import { RateChangesCard } from "@/components/notifications/manage/cards";
import { ErrorState } from "@/components/shared/error-state";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboard } from "@/lib/api/generated/endpoints/dashboard/dashboard";
import type { DashboardAction, DashboardToday, DashboardTrends } from "@/lib/api/generated/model";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

import { DailyChart } from "./daily-chart";

interface Tile {
  key: string;
  href: string;
  label: string;
  value: number;
  detail?: ReactNode;
  icon: LucideIcon;
  /** Red rather than amber while above zero: something failed or is overdue. */
  urgent?: boolean;
}

function ActionTile({ tile }: { tile: Tile }) {
  const t = useTranslations("dashboard.action");
  const waiting = tile.value > 0;
  const Icon = tile.icon;
  return (
    <Link
      href={tile.href}
      className="block h-full rounded-xl focus-visible:ring-2"
      aria-label={`${tile.label}: ${tile.value}`}
    >
      <Card className={cn("hover:bg-muted h-full transition-colors", !waiting && "opacity-80")}>
        <CardContent className="flex items-start gap-3 py-4">
          <span
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-lg",
              !waiting
                ? "bg-muted text-muted-foreground"
                : tile.urgent
                  ? "bg-destructive/10 text-destructive"
                  : "bg-warning/15 text-warning-strong",
            )}
          >
            <Icon aria-hidden className="size-5" />
          </span>
          <span className="min-w-0">
            <span className="text-muted-foreground block text-sm">{tile.label}</span>
            <span className="block text-2xl font-semibold tabular-nums">{tile.value}</span>
            <span className="text-muted-foreground block text-xs">
              {waiting ? tile.detail : t("clear")}
            </span>
          </span>
        </CardContent>
      </Card>
    </Link>
  );
}

/** What needs action today, each only for those allowed to see it (the server sends null). */
function useTiles(action: DashboardAction): Tile[] {
  const t = useTranslations("dashboard.action");
  const tiles: (Tile | null)[] = [
    action.new_orders === null
      ? null
      : {
          key: "new",
          href: "/manage/orders",
          label: t("newOrders"),
          value: action.new_orders,
          icon: ClipboardList,
        },
    action.on_hold === null
      ? null
      : {
          key: "hold",
          href: "/manage/orders",
          label: t("onHold"),
          value: action.on_hold,
          icon: ShieldAlert,
        },
    action.backorders_to_confirm === null
      ? null
      : {
          key: "backorders",
          href: "/manage/backorders",
          label: t("backorders"),
          value: action.backorders_to_confirm,
          icon: PackageSearch,
        },
    action.to_pack === null
      ? null
      : {
          key: "pack",
          href: "/manage/orders/shipments",
          label: t("toPack"),
          value: action.to_pack,
          icon: PackageCheck,
        },
    action.failed_irns === null
      ? null
      : {
          key: "irns",
          href: "/manage/invoices/einvoices",
          label: t("failedIrns"),
          value: action.failed_irns,
          icon: FileWarning,
          urgent: true,
        },
    action.failed_ewaybills === null
      ? null
      : {
          key: "ewaybills",
          href: "/manage/invoices/ewaybills",
          label: t("failedEwaybills"),
          value: action.failed_ewaybills,
          icon: Truck,
          urgent: true,
        },
    action.handover === null
      ? null
      : {
          key: "handover",
          href: "/manage/payments/handover",
          label: t("handover"),
          value: action.handover.count,
          detail: <MoneyText value={action.handover.amount} />,
          icon: Wallet,
        },
    action.overdue === null
      ? null
      : {
          key: "overdue",
          href: "/manage/receivables",
          label: t("overdue"),
          value: action.overdue.shops,
          detail: (
            <>
              {t("overdueBody", { count: action.overdue.shops })} ·{" "}
              <MoneyText value={action.overdue.amount} />
            </>
          ),
          icon: AlertTriangle,
          urgent: true,
        },
    action.low_stock === null
      ? null
      : {
          key: "stock",
          href: "/manage/stock?status=LOW",
          label: t("lowStock"),
          value: action.low_stock.low + action.low_stock.out,
          detail: t("lowStockBody", { out: action.low_stock.out }),
          icon: Boxes,
        },
    // ADR-053: stock planning and purchasing, while their modules are on.
    action.to_reorder === null
      ? null
      : {
          key: "reorder",
          href: "/manage/stock/reorder",
          label: t("toReorder"),
          value: action.to_reorder,
          icon: ShoppingCart,
        },
    action.late_purchase_orders === null
      ? null
      : {
          key: "latePurchaseOrders",
          href: "/manage/purchasing/orders?late=1",
          label: t("latePurchaseOrders"),
          value: action.late_purchase_orders,
          detail: t("latePurchaseOrdersBody"),
          icon: Truck,
          urgent: true,
        },
    // ADR-056: shops that stopped ordering, are slowing or never ordered, not contacted lately.
    action.win_back === null || action.win_back === undefined
      ? null
      : {
          key: "winBack",
          href: "/manage/retailers/activity",
          label: t("winBack"),
          value: action.win_back,
          detail: t("winBackBody"),
          icon: UserX,
        },
  ];
  return tiles.filter((tile): tile is Tile => tile !== null);
}

function ActionSection({ action }: { action: DashboardAction }) {
  const t = useTranslations("dashboard.action");
  const tiles = useTiles(action);
  if (!tiles.length) return null;
  return (
    <section aria-labelledby="dashboard-action" className="space-y-3">
      <h2 id="dashboard-action" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {tiles.map((tile) => (
          <li key={tile.key}>
            <ActionTile tile={tile} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function TodaySection({ today }: { today: DashboardToday }) {
  const t = useTranslations("dashboard.today");
  if (today.orders_received === null && today.billed === null) return null;
  return (
    <section aria-labelledby="dashboard-today" className="space-y-3">
      <h2 id="dashboard-today" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {today.orders_received ? (
          <Card>
            <CardContent className="py-4">
              <p className="text-muted-foreground text-sm">{t("ordersReceived")}</p>
              <p className="text-2xl font-semibold">
                <MoneyText value={today.orders_received.amount} />
              </p>
              <p className="text-muted-foreground text-xs">
                {t("ordersReceivedBody", { count: today.orders_received.count })}
              </p>
            </CardContent>
          </Card>
        ) : null}
        {today.billed !== null ? (
          <Card>
            <CardContent className="py-4">
              <p className="text-muted-foreground text-sm">{t("billed")}</p>
              <p className="text-2xl font-semibold">
                <MoneyText value={today.billed} />
              </p>
              <p className="text-muted-foreground text-xs">{t("billedBody")}</p>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </section>
  );
}

function TopList({
  title,
  rows,
  href,
}: {
  title: string;
  rows: { id: string; name: string; total: string }[];
  href: (id: string) => string;
}) {
  const t = useTranslations("dashboard.trends");
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length ? (
          <ol className="space-y-1">
            {rows.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-3 text-sm">
                <Link
                  href={href(row.id)}
                  className="text-primary inline-flex min-h-11 min-w-0 items-center truncate underline-offset-4 hover:underline md:min-h-8"
                >
                  <span className="truncate">{row.name}</span>
                </Link>
                <MoneyText value={row.total} className="shrink-0" />
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground text-sm">{t("nothingYet")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function TrendsSection({ trends }: { trends: DashboardTrends }) {
  const t = useTranslations("dashboard.trends");
  const money = (value: string) => (value ? formatMoney(value) : "—");
  return (
    <section aria-labelledby="dashboard-trends" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 id="dashboard-trends" className="text-lg font-semibold">
          {t("title")}
        </h2>
        <Link
          href="/manage/reports"
          className="text-primary inline-flex min-h-11 items-center text-sm underline-offset-4 hover:underline md:min-h-8"
        >
          {t("allReports")}
        </Link>
      </div>
      <Card>
        <CardContent className="space-y-3 py-4">
          <div>
            <p className="text-muted-foreground text-sm">{t("billed")}</p>
            <p className="text-2xl font-semibold">
              <MoneyText value={trends.billed_30_days} />
            </p>
            <p className="text-muted-foreground text-xs">
              {t("previous", { amount: formatMoney(trends.billed_previous_30_days) })}
            </p>
          </div>
          <DailyChart
            rows={trends.days}
            caption={t("chartSummary", {
              amount: formatMoney(trends.billed_30_days),
              previous: formatMoney(trends.billed_previous_30_days),
            })}
            dateLabel={t("date")}
            series={[
              {
                key: "billed",
                label: t("thisPeriod"),
                color: "var(--primary)",
                format: money,
              },
              {
                key: "previous",
                label: t("previousPeriod"),
                color: "var(--muted-foreground)",
                dashed: true,
                format: money,
              },
            ]}
          />
        </CardContent>
      </Card>
      <div className="grid gap-3 lg:grid-cols-3">
        <TopList
          title={t("topProducts")}
          rows={trends.top_products.map((p) => ({
            id: p.product_id,
            name: p.name,
            total: p.total,
          }))}
          href={(id) => `/manage/products/${id}`}
        />
        <TopList
          title={t("topShops")}
          rows={trends.top_shops.map((s) => ({ id: s.retailer_id, name: s.name, total: s.total }))}
          href={(id) => `/manage/retailers/${id}`}
        />
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("shops")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{t("newShops", { count: trends.new_shops })}</p>
            <p>{t("repeatShops", { count: trends.repeat_shops })}</p>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

/** The distributor opens on what needs action today (spec §8, ADR-050 item 11), then today's
 * orders and billing, then the last 30 days. One request; each part only with its permission. */
export function DistributorDashboard() {
  const t = useTranslations("dashboard");
  const query = useDashboard({ query: { refetchInterval: 60_000 } });
  const body = query.data?.data;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <FailedEWayBillsAlert />
      {query.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : query.error || !body ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-8">
          {body.own_shops ? (
            <p className="text-muted-foreground flex items-center gap-2 text-sm">
              <Info aria-hidden className="size-4 shrink-0" />
              {t("ownShops")}
            </p>
          ) : null}
          <ActionSection action={body.action} />
          <TodaySection today={body.today} />
          {body.trends ? <TrendsSection trends={body.trends} /> : null}
        </div>
      )}
      <ComplianceCards />
      <div className="mt-8 max-w-2xl">
        <RateChangesCard />
      </div>
    </>
  );
}
