"use client";

import { ClipboardCheck, PackagePlus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ProductPlanningCard } from "@/components/planning/product-planning";
import { ErrorState } from "@/components/shared/error-state";
import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  stockReorderLevelUpdate,
  useStockRetrieve,
} from "@/lib/api/generated/endpoints/inventory/inventory";
import type { StockDetail } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

import { MovementsTable } from "./movements";
import { BackTo, CountCard } from "./shared";

function ReorderLevel({ product, onSaved }: { product: StockDetail; onSaved: () => void }) {
  const t = useTranslations("stock.detail");
  const { can } = useAuth();
  const errors = useErrorText();
  const editable = can("products.manage") || can("stock.adjust");
  const [value, setValue] = useState(Number(product.reorder_level) ? product.reorder_level : "");
  const [saving, setSaving] = useState(false);
  const unit = product.unit.code;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await stockReorderLevelUpdate(product.id, { reorder_level: value.trim() || "0" });
      toast.success(t("reorderSaved"));
      onSaved();
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("reorderTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-muted-foreground text-sm">{t("reorderHelp")}</p>
        {editable ? (
          <form onSubmit={save} className="flex items-end gap-2">
            <label className="flex-1 text-sm">
              <span className="mb-1 block font-medium">{t("reorderLabel", { unit })}</span>
              <Input
                inputMode="decimal"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={t("notSet")}
                className="h-11"
              />
            </label>
            <Button type="submit" className="min-h-11" disabled={saving}>
              {t("save")}
            </Button>
          </form>
        ) : (
          <p className="font-medium">
            {Number(product.reorder_level) ? (
              <QtyText value={product.reorder_level} unit={unit} />
            ) : (
              t("notSet")
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function StockDetailPage({ productId }: { productId: string }) {
  const t = useTranslations("stock.detail");
  const alertTypes = useTranslations("stock.alertTypes");
  const { can } = useAuth();
  const query = useStockRetrieve(productId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const product = query.data.data;
  const unit = product.unit.code;
  return (
    <>
      <BackTo href="/manage/stock">{t("back")}</BackTo>
      <PageHeader
        title={product.name}
        description={product.code}
        actions={
          <>
            {can("stock.inward") ? (
              <Button asChild className="min-h-10">
                <Link href={`/manage/stock/inwards/new?product=${product.id}`}>
                  <PackagePlus aria-hidden />
                  {t("receive")}
                </Link>
              </Button>
            ) : null}
            {can("stock.adjust") ? (
              <Button asChild variant="outline" className="min-h-10">
                <Link href={`/manage/stock/adjustments/new?product=${product.id}`}>
                  <ClipboardCheck aria-hidden />
                  {t("adjust")}
                </Link>
              </Button>
            ) : null}
            {can("products.view") ? (
              <Button asChild variant="ghost" className="min-h-10">
                <Link href={`/manage/products/${product.id}`}>{t("productDetails")}</Link>
              </Button>
            ) : null}
          </>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <CountCard
          label={t("available")}
          value={
            <span className="flex flex-wrap items-center gap-2">
              <QtyText value={product.available} unit={unit} />
              <StatusBadge status={product.status} className="text-xs" />
            </span>
          }
        />
        <CountCard label={t("onHand")} value={<QtyText value={product.on_hand} unit={unit} />} />
        <CountCard label={t("reserved")} value={<QtyText value={product.reserved} unit={unit} />} />
        <CountCard
          label={t("backordered")}
          value={<QtyText value={product.backordered} unit={unit} />}
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <section aria-labelledby="movements-title" className="min-w-0 space-y-3">
          <h2 id="movements-title" className="text-lg font-semibold">
            {t("movements")}
          </h2>
          <MovementsTable productId={product.id} withProduct={false} emptyText={t("noMovements")} />
        </section>
        <div className="space-y-6">
          <ProductPlanningCard productId={product.id} unit={unit} />
          <ReorderLevel
            key={product.reorder_level}
            product={product}
            onSaved={() => void query.refetch()}
          />
          {can("costs.view") ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("costTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                {product.cost_price ? (
                  <p className="text-lg font-semibold">
                    <MoneyText value={product.cost_price} />{" "}
                    <span className="text-muted-foreground text-sm font-normal">
                      {t("perUnit", { unit })}
                    </span>
                  </p>
                ) : (
                  <p className="text-muted-foreground">{t("noCost")}</p>
                )}
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("alertsTitle")}</CardTitle>
            </CardHeader>
            <CardContent>
              {product.open_alerts.length ? (
                <ul className="space-y-2">
                  {product.open_alerts.map((alert) => (
                    <li key={alert.id} className="flex items-center justify-between gap-2 text-sm">
                      <span className="font-medium">{alertTypes(alert.alert_type)}</span>
                      <span className="text-muted-foreground">
                        <DateText value={alert.opened_at} />
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-sm">{t("noAlerts")}</p>
              )}
            </CardContent>
          </Card>
          {product.barcodes.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("barcodes")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-wrap gap-2 font-mono text-sm">
                  {product.barcodes.map((code) => (
                    <li key={code} className="bg-muted rounded px-2 py-1">
                      {code}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}

/** On the product page: the stock at a glance, linking to its stock page. */
export function ProductStockCard({ productId }: { productId: string }) {
  const t = useTranslations("stock.detail");
  const query = useStockRetrieve(productId);
  const product = query.data?.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("stockTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {product ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">{t("available")}</span>
              <span className="flex items-center gap-2 font-semibold">
                <QtyText value={product.available} unit={product.unit.code} />
                <StatusBadge status={product.status} />
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">{t("onHand")}</span>
              <QtyText value={product.on_hand} unit={product.unit.code} />
            </div>
          </>
        ) : query.error ? (
          <p className="text-muted-foreground">{t("stockUnavailable")}</p>
        ) : (
          <p className="text-muted-foreground">…</p>
        )}
        <Button asChild variant="outline" className="min-h-10 w-full">
          <Link href={`/manage/stock/${productId}`}>{t("stockLink")}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
