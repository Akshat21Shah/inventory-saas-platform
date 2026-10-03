"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Link2Off } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FieldsDialog } from "@/components/shared/fields-dialog";
import { DateText } from "@/components/shared/money-text";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  documentLinksRevoke,
  getDocumentLinksQueryKey,
  getRetailerReminderPauseQueryKey,
  getRetailerWhatsappConsentQueryKey,
  retailerReminderPauseEnd,
  retailerReminderPauseSet,
  retailerWhatsappConsentUpdate,
  useDocumentLinks,
  useRetailerReminderPause,
  useRetailerWhatsappConsent,
  useTaxUpcomingRateChanges,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type { DocumentLinkKindEnum } from "@/lib/api/generated/model";
import { formatDate } from "@/lib/format";

function Loading() {
  return <Skeleton className="h-10 w-full" />;
}

/** Retailer page: whether the shop agreed to WhatsApp, with who recorded it; staff record
 * agreement only after confirming the shop agreed, and can stop WhatsApp. */
export function RetailerConsentCard({ retailerId }: { retailerId: string }) {
  const t = useTranslations("notifyAdmin.consent");
  const { can } = useAuth();
  const client = useQueryClient();
  const query = useRetailerWhatsappConsent(retailerId, {
    query: { enabled: can("retailers.view") },
  });
  const consent = query.data?.data;
  const set = async (agreed: boolean, confirmed: boolean) => {
    const response = await retailerWhatsappConsentUpdate(retailerId, { agreed, confirmed });
    client.setQueryData(getRetailerWhatsappConsentQueryKey(retailerId), response);
    toast.success(t("saved"));
  };
  if (!can("retailers.view")) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {query.isLoading || !consent ? (
          <Loading />
        ) : (
          <>
            {!consent.whatsapp_available ? (
              <p className="text-muted-foreground">{t("unavailable")}</p>
            ) : null}
            <p>
              {consent.opted_in && consent.opted_in_at
                ? t("on", {
                    date: formatDate(consent.opted_in_at),
                    source: consent.source ? t(`sources.${consent.source}`) : "",
                  })
                : consent.opted_out_at
                  ? t("offSince", { date: formatDate(consent.opted_out_at) })
                  : t("off")}
            </p>
            {can("retailers.manage") ? (
              consent.opted_in ? (
                <ConfirmDialog
                  destructive
                  trigger={
                    <Button variant="outline" className="min-h-10 w-full max-md:min-h-11">
                      {t("turnOff")}
                    </Button>
                  }
                  title={t("stopTitle")}
                  description={t("stopBody")}
                  confirmLabel={t("turnOff")}
                  onConfirm={() => set(false, false)}
                />
              ) : (
                <FieldsDialog
                  trigger={
                    <Button variant="outline" className="min-h-10 w-full max-md:min-h-11">
                      {t("turnOn")}
                    </Button>
                  }
                  title={t("confirmTitle")}
                  description={t("confirmBody")}
                  fields={[{ name: "confirmed", label: t("confirm"), kind: "bool" }]}
                  initial={{ confirmed: false }}
                  submitLabel={t("turnOn")}
                  onSubmit={(values) => set(true, values.confirmed === true)}
                />
              )
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Retailer page: pause payment reminders with a reason and an optional end date, or resume. */
export function ReminderPauseCard({ retailerId }: { retailerId: string }) {
  const t = useTranslations("notifyAdmin.pause");
  const { can } = useAuth();
  const client = useQueryClient();
  const allowed = can("credit.manage") || can("ledger.view");
  const query = useRetailerReminderPause(retailerId, { query: { enabled: allowed } });
  if (!allowed) return null;
  const pause = query.data?.data.pause;
  const store = (response: Awaited<ReturnType<typeof retailerReminderPauseEnd>>) =>
    client.setQueryData(getRetailerReminderPauseQueryKey(retailerId), response);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {query.isLoading ? (
          <Loading />
        ) : pause ? (
          <>
            <p className="flex items-start gap-2">
              <CalendarClock aria-hidden className="text-warning-strong mt-0.5 size-4 shrink-0" />
              <span className="break-words">{t("paused", { reason: pause.reason })}</span>
            </p>
            <p className="text-muted-foreground">
              {pause.until ? t("until", { date: formatDate(pause.until) }) : t("untilResumed")}
            </p>
            {can("credit.manage") ? (
              <Button
                variant="outline"
                className="min-h-10 w-full max-md:min-h-11"
                onClick={async () => {
                  store(await retailerReminderPauseEnd(retailerId));
                  toast.success(t("resumed"));
                }}
              >
                {t("resume")}
              </Button>
            ) : null}
          </>
        ) : (
          <>
            <p className="text-muted-foreground">{t("active")}</p>
            {can("credit.manage") ? (
              <FieldsDialog
                trigger={
                  <Button variant="outline" className="min-h-10 w-full max-md:min-h-11">
                    {t("pause")}
                  </Button>
                }
                title={t("pauseTitle")}
                description={t("pauseBody")}
                fields={[
                  {
                    name: "reason",
                    label: t("reason"),
                    required: true,
                    hint: t("reasonPlaceholder"),
                  },
                  { name: "until", label: t("untilField"), kind: "date" },
                ]}
                initial={{ reason: "", until: "" }}
                submitLabel={t("pause")}
                onSubmit={async (values) => {
                  store(
                    await retailerReminderPauseSet(retailerId, {
                      reason: String(values.reason ?? ""),
                      until: values.until ? String(values.until) : null,
                    }),
                  );
                  toast.success(t("paused_toast"));
                }}
              />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

const MANAGE: Record<DocumentLinkKindEnum, string> = {
  INVOICE: "invoices.manage",
  CREDIT_NOTE: "invoices.manage",
  ORDER_CONFIRMATION: "orders.manage",
  RECEIPT: "payments.record",
  REFUND_VOUCHER: "payments.record",
  PURCHASE_ORDER: "purchasing.manage",
};

/** A document's page: the links sent by WhatsApp or email (opens, expiry), and withdrawing them.
 * Shown only to staff who manage the document. */
export function DocumentLinksCard({
  kind,
  objectId,
}: {
  kind: DocumentLinkKindEnum;
  objectId: string;
}) {
  const t = useTranslations("notifyAdmin.links");
  const { can } = useAuth();
  const client = useQueryClient();
  const allowed = can(MANAGE[kind]);
  const params = { kind, object_id: objectId };
  const query = useDocumentLinks(params, { query: { enabled: allowed } });
  if (!allowed) return null;
  const links = query.data?.data ?? [];
  const live = links.filter((link) => link.is_live).length;
  return (
    <section className="space-y-2 rounded-xl border p-4 text-sm" aria-labelledby="links-heading">
      <h2 id="links-heading" className="font-semibold">
        {t("title")}
      </h2>
      <p className="text-muted-foreground text-xs">{t("description")}</p>
      {query.isLoading ? (
        <Loading />
      ) : !links.length ? (
        <p className="text-muted-foreground">{t("none")}</p>
      ) : (
        <ul className="divide-y">
          {links.map((link) => (
            <li key={link.id} className="flex flex-wrap justify-between gap-x-3 gap-y-1 py-2">
              <span>
                <DateText value={link.created_at} withTime />
              </span>
              <span className="text-muted-foreground">
                {t("opened", { count: link.open_count ?? 0 })} ·{" "}
                {link.revoked_at
                  ? t("revoked")
                  : link.is_live
                    ? t("expires", { date: formatDate(link.expires_at) })
                    : t("expired")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {live ? (
        <ConfirmDialog
          destructive
          trigger={
            <Button variant="outline" className="min-h-10 max-md:min-h-11">
              <Link2Off aria-hidden />
              {t("revoke")}
            </Button>
          }
          title={t("revokeTitle")}
          description={t("revokeBody")}
          confirmLabel={t("revoke")}
          onConfirm={async () => {
            const response = await documentLinksRevoke({ kind, object_id: objectId });
            toast.success(t("revokedToast", { count: response.data.revoked }));
            await client.invalidateQueries({ queryKey: getDocumentLinksQueryKey(params) });
          }}
        />
      ) : null}
    </section>
  );
}

/** Dashboard: GST rates of products changing in the next 30 days (nothing when none). */
export function RateChangesCard() {
  const t = useTranslations("notifyAdmin.rates");
  const { can } = useAuth();
  const changes =
    useTaxUpcomingRateChanges({ query: { enabled: can("products.view") } }).data?.data ?? [];
  if (!can("products.view") || !changes.length) return null;
  const shown = changes.slice(0, 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-1 text-sm">
          {shown.map((change) => (
            <li key={`${change.product_id}-${change.effective_from}`} className="break-words">
              {t("row", {
                product: change.product,
                from: `${Number(change.old_rate)}%`,
                to: `${Number(change.new_rate)}%`,
                date: formatDate(change.effective_from),
              })}
            </li>
          ))}
          {changes.length > shown.length ? (
            <li className="text-muted-foreground">
              {t("more", { count: changes.length - shown.length })}
            </li>
          ) : null}
        </ul>
      </CardContent>
    </Card>
  );
}
