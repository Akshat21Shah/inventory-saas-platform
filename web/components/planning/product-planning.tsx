"use client";

import { useAuth } from "@/components/auth/auth-provider";
import { DateText } from "@/components/shared/money-text";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProductStats } from "@/lib/api/generated/endpoints/planning/planning";
import { useProductOnOrder } from "@/lib/api/generated/endpoints/purchasing/purchasing";
import { formatQty } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";

import { useDemandRate, useStockLasts } from "./words";

/**
 * What is on order for a product and when (purchasing on; for anyone who sees orders or stock,
 * never a supplier or a price), for the product and backorder pages and order lines.
 */
export function OnOrderLine({ productId, unit }: { productId: string; unit?: string }) {
  const t = useTranslations("planning.onOrder");
  const { can, feature } = useAuth();
  const enabled = feature("purchasing") && (can("orders.view") || can("stock.view"));
  const query = useProductOnOrder(productId, { query: { enabled } });
  const found = query.data?.data;
  if (!enabled || !found || Number(found.quantity) <= 0) return null;
  return (
    <p className="text-sm">
      {t("line", { qty: formatQty(found.quantity), unit: unit ?? "" })}
      {found.expected_date ? (
        <>
          {", "}
          {t("expected")} <DateText value={found.expected_date} />
        </>
      ) : null}
      {found.late ? (
        <Badge variant="destructive" className="ml-1">
          {t("late")}
        </Badge>
      ) : null}
    </p>
  );
}

/** A product's stock planning figures (ADR-053 item 3) and what is on order. */
export function ProductPlanningCard({ productId, unit }: { productId: string; unit: string }) {
  const t = useTranslations("planning.stats");
  const { can, feature } = useAuth();
  const planning = feature("stock_planning") && (can("purchasing.view") || can("stock.view"));
  const purchasing = feature("purchasing") && (can("orders.view") || can("stock.view"));
  const stats = useProductStats(productId, { query: { enabled: planning } });
  const rate = useDemandRate();
  const stockLasts = useStockLasts();
  const notSelling = useTranslations("planning.notSelling");
  if (!planning && !purchasing) return null;
  const figures = stats.data?.status === 200 ? stats.data.data : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <OnOrderLine productId={productId} unit={unit} />
        {!planning ? null : stats.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : stats.isError ? (
          <p className="text-muted-foreground">{t("failed")}</p>
        ) : !figures ? (
          <p className="text-muted-foreground">{t("notYet")}</p>
        ) : (
          <>
            {figures.not_selling ? (
              <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
                {notSelling("note")}
              </p>
            ) : null}
            <Fact label={t("ordered")}>
              {Number(figures.demand_qty) > 0 ? rate(figures.demand_rate, unit) : t("noDemand")}
            </Fact>
            <p className="text-muted-foreground text-xs">
              {t("demandNote", { days: figures.demand_days })}
            </p>
            <Fact label={t("daysOfStock")}>
              {stockLasts(figures.available, figures.days_of_stock) ?? t("noDemand")}
            </Fact>
            <Fact label={t("abc")}>
              {figures.abc_class ? t(`abcClasses.${figures.abc_class}`) : t("noSales")}
            </Fact>
            <Fact label={t("movement")}>
              {figures.movement_class
                ? t(`movementClasses.${figures.movement_class}`)
                : t("noMovement")}
            </Fact>
            <Fact label={t("lastSold")}>
              {figures.last_sale_date ? <DateText value={figures.last_sale_date} /> : t("never")}
            </Fact>
            <p className="text-muted-foreground text-xs">
              {t("worked")} <DateText value={figures.computed_at} withTime />
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <p className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </p>
  );
}
