"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Lock, Megaphone } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ErrorState } from "@/components/shared/error-state";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  getShopNotificationPreferencesQueryKey,
  getShopWhatsappConsentQueryKey,
  shopNotificationPreferencesUpdate,
  shopWhatsappConsentPrompted,
  shopWhatsappConsentUpdate,
  useShopAnnouncements,
  useShopNotificationPreferences,
  useShopWhatsappConsent,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { NotificationChannelEnum, PreferenceRow } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

const labelKey = (code: string) => code.replace(".", "_");

/** The distributor's current notices, on the shop's home (nothing when there are none). */
export function ShopAnnouncements() {
  const t = useTranslations("shop.messages");
  const notices = useShopAnnouncements().data?.data ?? [];
  if (!notices.length) return null;
  return (
    <section aria-label={t("announcements")} className="space-y-2">
      {notices.map((notice) => (
        <div key={notice.id} className="bg-brand-50 flex gap-3 rounded-xl border p-4">
          <Megaphone aria-hidden className="text-brand-700 mt-0.5 size-5 shrink-0" />
          <div className="min-w-0 space-y-1">
            <p className="font-semibold break-words">{notice.title}</p>
            <p className="text-sm break-words whitespace-pre-line">{notice.body}</p>
          </div>
        </div>
      ))}
    </section>
  );
}

/** Asked once after sign-in, if the distributor sends WhatsApp messages and the shop hasn't
 * agreed yet: "Yes" records the shop's consent; "Not now" (or closing) doesn't ask again. */
export function WhatsAppPrompt() {
  const t = useTranslations("shop.messages");
  const { me } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const consent = useShopWhatsappConsent().data?.data;
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const open = Boolean(consent?.prompt && consent.whatsapp_available) && !dismissed;

  const answer = async (agreed: boolean) => {
    setBusy(true);
    try {
      const response = agreed
        ? await shopWhatsappConsentUpdate({ agreed: true })
        : await shopWhatsappConsentPrompted();
      client.setQueryData(getShopWhatsappConsentQueryKey(), response);
      if (agreed) toast.success(t("turnedOn"));
      setDismissed(true);
    } catch (error) {
      toast.error(message(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!next && !busy ? void answer(false) : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("promptTitle")}</DialogTitle>
          <DialogDescription>
            {t("promptBody", { distributor: me?.tenant?.name ?? "", mobile: me?.phone ?? "" })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy}
            onClick={() => void answer(false)}
          >
            {t("promptNo")}
          </Button>
          <Button className="min-h-11" disabled={busy} onClick={() => void answer(true)}>
            {t("promptYes")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function WhatsAppCard() {
  const t = useTranslations("shop.messages");
  const { me } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopWhatsappConsent();
  const consent = query.data?.data;
  const [busy, setBusy] = useState(false);
  if (query.isLoading) return <CardSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!consent) return null;
  const mobile = me?.phone ?? "";

  const change = async (agreed: boolean) => {
    setBusy(true);
    try {
      const response = await shopWhatsappConsentUpdate({ agreed });
      client.setQueryData(getShopWhatsappConsentQueryKey(), response);
      toast.success(agreed ? t("turnedOn") : t("turnedOff"));
    } catch (error) {
      toast.error(message(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-2 rounded-xl border p-4" aria-labelledby="whatsapp-heading">
      <h2 id="whatsapp-heading" className="font-semibold">
        {t("whatsappTitle")}
      </h2>
      {consent.whatsapp_available ? (
        <label className="flex min-h-11 items-center justify-between gap-4">
          <span className="text-muted-foreground text-sm">
            {consent.opted_in ? t("whatsappOn", { mobile }) : t("whatsappOff", { mobile })}
          </span>
          <Switch
            aria-label={t("whatsappSwitch")}
            checked={consent.opted_in}
            disabled={busy}
            onCheckedChange={(value) => void change(value)}
          />
        </label>
      ) : (
        <p className="text-muted-foreground text-sm">{t("whatsappUnavailable")}</p>
      )}
    </section>
  );
}

function PreferenceGroup({
  rows,
  whatsappOn,
  onChange,
  busy,
}: {
  rows: PreferenceRow[];
  whatsappOn: boolean;
  onChange: (event: string, channel: NotificationChannelEnum, enabled: boolean) => void;
  busy: boolean;
}) {
  const t = useTranslations("shop.messages");
  const n = useTranslations("notifications");
  return (
    <ul className="divide-y rounded-xl border">
      {rows.map((row) => {
        const label = n(`shopEvents.${labelKey(row.event)}`);
        return (
          <li key={row.event} className="space-y-2 p-4">
            <p className="font-medium">{label}</p>
            {row.compulsory ? (
              <p className="text-muted-foreground flex items-center gap-1 text-xs">
                <Lock aria-hidden className="size-3" />
                {t("always")}
              </p>
            ) : null}
            <ul className="flex flex-wrap gap-x-6 gap-y-1">
              {row.channels.map((channel) => {
                const needsWhatsApp = channel.channel === "WHATSAPP" && !whatsappOn;
                return (
                  <li key={channel.channel}>
                    <label className="flex min-h-11 items-center gap-2 text-sm">
                      <Switch
                        aria-label={t("switchLabel", {
                          event: label,
                          channel: n(`channels.${channel.channel}`),
                        })}
                        checked={channel.enabled && !needsWhatsApp}
                        disabled={channel.locked || needsWhatsApp || busy}
                        onCheckedChange={(value) => onChange(row.event, channel.channel, value)}
                      />
                      {n(`channels.${channel.channel}`)}
                    </label>
                  </li>
                );
              })}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

/** Account → Messages: WhatsApp on or off, and which messages come on which channel. */
export function ShopMessagesPage() {
  const t = useTranslations("shop.messages");
  const n = useTranslations("notifications");
  const money = useTranslations("shop.money");
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopNotificationPreferences();
  const consent = useShopWhatsappConsent().data?.data;
  const [busy, setBusy] = useState(false);
  const rows = query.data?.data ?? [];
  const groups = [...new Set(rows.map((r) => r.group))];

  const change = async (event: string, channel: NotificationChannelEnum, enabled: boolean) => {
    setBusy(true);
    try {
      const response = await shopNotificationPreferencesUpdate({ event, channel, enabled });
      client.setQueryData(getShopNotificationPreferencesQueryKey(), response);
      toast.success(t("saved"));
    } catch (error) {
      toast.error(message(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Link
        href="/shop/account"
        className="text-muted-foreground inline-flex min-h-11 items-center gap-1 text-sm hover:underline"
      >
        <ChevronLeft aria-hidden className="size-4" />
        {money("title")}
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("body")}</p>
      </div>
      <WhatsAppCard />
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <p className="text-muted-foreground text-sm">{t("alwaysHint")}</p>
          {groups.map((group) => (
            <section key={group} className="space-y-2" aria-labelledby={`group-${group}`}>
              <h2 id={`group-${group}`} className="text-lg font-semibold">
                {n(`groups.${group}`)}
              </h2>
              <PreferenceGroup
                rows={rows.filter((r) => r.group === group)}
                whatsappOn={Boolean(consent?.opted_in && consent.whatsapp_available)}
                onChange={(event, channel, enabled) => void change(event, channel, enabled)}
                busy={busy}
              />
            </section>
          ))}
        </>
      )}
    </div>
  );
}
