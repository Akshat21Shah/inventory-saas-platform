"use client";

import { AlertTriangle, FileCheck2, FileClock, Truck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAuth } from "@/components/auth/auth-provider";
import { KpiCard } from "@/components/shared/kpi-card";
import { Button } from "@/components/ui/button";
import {
  useEinvoicesCounts,
  useEwaybillsCounts,
  useEwaybillsList,
} from "@/lib/api/generated/endpoints/compliance/compliance";

/** Failed e-way bills (backend checkpoint change 4): shown at the top of the dashboard until
 * each is fixed, naming the shipment, vehicle and the portal's reason, with a link to retry. */
export function FailedEWayBillsAlert() {
  const t = useTranslations("compliance.dashboard");
  const { can, feature } = useAuth();
  const on = feature("ewaybill") && can("compliance.manage");
  const failed = useEwaybillsList(
    { needs_action: true, page_size: 5 },
    { query: { enabled: on, refetchInterval: 60_000 } },
  );
  const counts = useEwaybillsCounts({ query: { enabled: on, refetchInterval: 60_000 } });
  const rows = failed.data?.data.results ?? [];
  if (!on || !rows.length) return null;
  const total = counts.data?.data.failed ?? rows.length;
  return (
    <section
      role="alert"
      aria-labelledby="failed-ewaybills"
      className="border-destructive/40 bg-destructive/5 mb-6 space-y-3 rounded-xl border p-4"
    >
      <h2 id="failed-ewaybills" className="flex items-center gap-2 font-semibold">
        <AlertTriangle aria-hidden className="text-destructive size-5 shrink-0" />
        {t("failedTitle", { count: total })}
      </h2>
      <p className="text-sm">{t("failedBody")}</p>
      <ul className="bg-background divide-y rounded-lg border">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <span className="min-w-0 text-sm">
              <span className="block font-medium">
                {t("failedLine", {
                  shipment: row.shipment_number || row.invoice_number,
                  shop: row.shop_name,
                })}
              </span>
              <span className="text-muted-foreground block">
                {row.vehicle_number
                  ? t("vehicle", { vehicle: row.vehicle_number })
                  : t("noVehicle")}
              </span>
              <span className="text-destructive block">{row.error_message}</span>
            </span>
            <Button asChild className="min-h-10">
              <Link href={`/manage/invoices/${row.invoice_id}#ewaybill`}>{t("fix")}</Link>
            </Button>
          </li>
        ))}
      </ul>
      {total > rows.length ? (
        <Link
          href="/manage/invoices/ewaybills"
          className="inline-flex min-h-10 items-center text-sm font-medium hover:underline max-md:min-h-11"
        >
          {t("seeAll", { count: total })}
        </Link>
      ) : null}
    </section>
  );
}

/** IRNs and e-way bills waiting or failed, for staff who manage compliance. */
export function ComplianceCards() {
  const t = useTranslations("compliance.dashboard");
  const { can, feature } = useAuth();
  const manage = can("compliance.manage");
  const einvoiceOn = feature("einvoice") && manage;
  const ewaybillOn = feature("ewaybill") && manage;
  const irn = useEinvoicesCounts({ query: { enabled: einvoiceOn } }).data?.data;
  const ewb = useEwaybillsCounts({ query: { enabled: ewaybillOn } }).data?.data;
  if (!einvoiceOn && !ewaybillOn) return null;
  const cards = [
    ...(einvoiceOn
      ? [
          {
            href: "/manage/invoices/einvoices",
            label: t("irnWaiting"),
            value: irn?.pending,
            icon: FileClock,
          },
          {
            href: "/manage/invoices/einvoices",
            label: t("irnNearLimit"),
            value: irn?.near_report_by,
            icon: FileCheck2,
          },
        ]
      : []),
    ...(ewaybillOn
      ? [
          {
            href: "/manage/invoices/ewaybills",
            label: t("ewbWaiting"),
            value: ewb?.pending,
            icon: Truck,
          },
        ]
      : []),
  ];
  return (
    <section className="mt-8 space-y-3" aria-labelledby="compliance-heading">
      <h2 id="compliance-heading" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <li key={card.label}>
            <Link href={card.href} className="block rounded-xl focus-visible:ring-2">
              <KpiCard label={card.label} value={card.value ?? 0} icon={card.icon} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
