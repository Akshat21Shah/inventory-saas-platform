"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormSelect } from "@/components/shared/form-select";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  getNotificationTextsQueryKey,
  notificationTextPreview,
  notificationTextReset,
  notificationTextUpdate,
  useNotificationRules,
  useNotificationTexts,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type { NotificationTextsLocale, Text, TextPreview } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

import { eventKey, NotificationsNav } from "./nav";

const LOCALES: NotificationTextsLocale[] = ["en", "hi", "mr"];
const AUDIENCES = ["SHOP", "STAFF", "SUPPLIER"] as const;

function TextEditor({
  event,
  locale,
  text,
}: {
  event: string;
  locale: NotificationTextsLocale;
  text: Text;
}) {
  const t = useTranslations("notifyAdmin.texts");
  const n = useTranslations("notifications");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [subject, setSubject] = useState(text.subject);
  const [body, setBody] = useState(text.body);
  const [preview, setPreview] = useState<TextPreview | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const id = `${event}-${text.audience}-${text.channel}`;
  const audience = text.audience;
  const refresh = () =>
    client.invalidateQueries({ queryKey: getNotificationTextsQueryKey(event, { locale }) });

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setErrors({});
    try {
      await action();
      if (done) toast.success(done);
    } catch (thrown) {
      const byField = fields(thrown);
      setErrors(byField);
      if (!Object.keys(byField).length) toast.error(message(thrown));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby={`${id}-heading`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`${id}-heading`} className="font-semibold">
          {n(`channels.${text.channel}`)}
        </h2>
        <span className="text-muted-foreground text-xs">{t(`source.${text.source}`)}</span>
      </div>
      {!text.editable ? (
        <>
          <p className="text-muted-foreground flex items-center gap-1 text-xs">
            <Lock aria-hidden className="size-3" />
            {t("fixed")}
          </p>
          <p className="bg-muted/40 rounded-lg p-3 text-sm break-words whitespace-pre-line">
            {text.body}
          </p>
        </>
      ) : (
        <>
          <div className="space-y-1">
            <Label htmlFor={`${id}-subject`}>{t("subject")}</Label>
            <Input
              id={`${id}-subject`}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              aria-invalid={Boolean(errors.subject)}
              className="min-h-10"
            />
            {errors.subject ? <p className="text-destructive text-sm">{errors.subject}</p> : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${id}-body`}>{t("body")}</Label>
            <Textarea
              id={`${id}-body`}
              value={body}
              rows={4}
              onChange={(e) => setBody(e.target.value)}
              aria-invalid={Boolean(errors.body)}
            />
            {errors.body ? <p className="text-destructive text-sm">{errors.body}</p> : null}
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-xs">{t("variables")}</p>
            <ul className="flex flex-wrap gap-1">
              {text.variables.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => setBody((current) => `${current}{{ ${name} }}`)}
                    className="bg-muted hover:bg-muted/70 min-h-8 rounded-full px-2 font-mono text-xs max-md:min-h-11"
                    aria-label={t("insert", { name })}
                  >
                    {`{{ ${name} }}`}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {preview ? (
            <div className="bg-brand-50 space-y-1 rounded-lg p-3 text-sm" aria-live="polite">
              <p className="text-muted-foreground text-xs">{t("previewTitle")}</p>
              <p className="font-medium break-words">{preview.subject}</p>
              <p className="break-words whitespace-pre-line">{preview.body}</p>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="min-h-11"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const shown = await notificationTextPreview({
                    event,
                    channel: text.channel,
                    audience,
                    locale,
                    subject,
                    body,
                  });
                  setPreview(shown.data);
                })
              }
            >
              {t("preview")}
            </Button>
            <Button
              className="min-h-11"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await notificationTextUpdate(event, text.channel, {
                    audience,
                    locale,
                    subject,
                    body,
                  });
                  await refresh();
                }, t("saved"))
              }
            >
              {t("save")}
            </Button>
            {text.source === "tenant" ? (
              <Button
                variant="ghost"
                className="min-h-11"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await notificationTextReset(event, text.channel, { locale, audience });
                    await refresh();
                  }, t("resetDone"))
                }
              >
                {t("reset")}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

/** Settings → Messages → Message texts: the words of each message, per language. */
export function NotificationTextsPage() {
  const t = useTranslations("notifyAdmin.texts");
  const n = useTranslations("notifications");
  const events = useNotificationRules().data?.data.events ?? [];
  const [event, setEvent] = useState("order.accepted");
  const [locale, setLocale] = useState<NotificationTextsLocale>("en");
  const query = useNotificationTexts(event, { locale });
  const texts = query.data?.data ?? [];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <NotificationsNav />
      <div className="mb-6 grid gap-3 sm:grid-cols-[1fr_12rem]">
        <div className="space-y-1">
          <Label htmlFor="text-event">{t("event")}</Label>
          <FormSelect
            id="text-event"
            value={event}
            onValueChange={setEvent}
            options={(events.length ? events.map((e) => e.code) : [event]).map((code) => ({
              value: code,
              label: n(`events.${eventKey(code)}`),
            }))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="text-locale">{t("language")}</Label>
          <FormSelect
            id="text-locale"
            value={locale}
            onValueChange={(value) => setLocale(value as NotificationTextsLocale)}
            options={LOCALES.map((code) => ({ value: code, label: t(`languages.${code}`) }))}
          />
        </div>
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !texts.length ? (
        <EmptyState title={t("empty")} />
      ) : (
        <div className="space-y-8">
          {AUDIENCES.filter((audience) => texts.some((text) => text.audience === audience)).map(
            (audience) => (
              <section key={audience} className="space-y-4" aria-labelledby={`to-${audience}`}>
                <div className="space-y-1">
                  <h2 id={`to-${audience}`} className="text-lg font-semibold">
                    {t(`audiences.${audience}`)}
                  </h2>
                  <p className="text-muted-foreground text-sm">{t(`audienceHints.${audience}`)}</p>
                </div>
                {texts
                  .filter((text) => text.audience === audience)
                  .map((text) => (
                    <TextEditor
                      key={`${event}-${locale}-${audience}-${text.channel}-${text.source}-${text.body}`}
                      event={event}
                      locale={locale}
                      text={text}
                    />
                  ))}
              </section>
            ),
          )}
        </div>
      )}
    </>
  );
}
