"use client";

import { useTranslations } from "next-intl";

import { SubNav } from "@/components/shared/sub-nav";

/** Invoices and credit notes, with the invoicing settings for those who manage settings. */
export function BillingNav() {
  const t = useTranslations("billing.nav");
  return (
    <SubNav
      label={t("label")}
      items={[
        {
          href: "/manage/invoices",
          label: t("invoices"),
          match: (path) =>
            path === "/manage/invoices" || /^\/manage\/invoices\/[0-9a-f-]{36}$/.test(path),
        },
        { href: "/manage/invoices/credit-notes", label: t("creditNotes"), prefix: true },
        {
          href: "/manage/settings/policies/invoicing",
          label: t("settings"),
          permission: "settings.manage",
        },
      ]}
    />
  );
}

/** Payments, refunds, receivables and collections waiting for handover. */
export function PaymentsNav() {
  const t = useTranslations("billing.nav");
  return (
    <SubNav
      label={t("paymentsLabel")}
      items={[
        {
          href: "/manage/payments",
          label: t("payments"),
          match: (path) =>
            path === "/manage/payments" ||
            path === "/manage/payments/new" ||
            /^\/manage\/payments\/[0-9a-f-]{36}$/.test(path),
        },
        { href: "/manage/payments/refunds", label: t("refunds"), prefix: true },
        {
          href: "/manage/payments/handover",
          label: t("handover"),
          permission: "payments.record",
        },
        { href: "/manage/receivables", label: t("receivables"), permission: "ledger.view" },
        {
          href: "/manage/settings/policies/credit_payments",
          label: t("paymentSettings"),
          permission: "settings.manage",
        },
      ]}
    />
  );
}
