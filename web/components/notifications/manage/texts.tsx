"use client";

import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
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
  getNotificationTextsQueryOptions,
  notificationTextPreview,
  notificationTextReset,
  notificationTextUpdate,
  useNotificationRules,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type { Text, TextPreview } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { cn } from "@/lib/utils";

import { eventKey, NotificationsNav } from "./nav";

const AUDIENCES = ["SHOP", "STAFF", "SUPPLIER"] as const;

function TextEditor({
  event,
  locale,
  language,
  text,
}: {
  event: string;
  locale: string;
  language: string;
  text: Text;
}) {
  const t = useTranslations("notifyAdmin.texts");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [subject, setSubject] = useState(text.subject);
  const [body, setBody] = useState(text.body);
  const [preview, setPreview] = useState<TextPreview | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const id = `${event}-${text.audience}-${text.channel}-${locale}`;
  const audience = text.audience;
  // Every language's copy: which languages have the distributor's own words changes too.
  const refresh = () => client.invalidateQueries({ queryKey: getNotificationTextsQueryKey(event) });

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
    <section className="min-w-0 space-y-3" aria-labelledby={`${id}-heading`} lang={locale}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 id={`${id}-heading`} className="font-medium">
          {language}
        </h4>
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

/** The texts of one message (an audience's channel) in every language, side by side, with a
 * warning when the distributor has its own wording in some languages only (owner, ADR-060). */
function MessageTexts({
  event,
  audience,
  channel,
  byLanguage,
}: {
  event: string;
  audience: string;
  channel: string;
  byLanguage: { code: string; native: string; text: Text }[];
}) {
  const t = useTranslations("notifyAdmin.texts");
  const n = useTranslations("notifications");
  const id = `${event}-${audience}-${channel}`;
  const edited = new Set(byLanguage.flatMap(({ text }) => text.edited_locales ?? []));
  const editable = byLanguage.some(({ text }) => text.editable);
  const names = (codes: string[]) =>
    byLanguage
      .filter(({ code }) => codes.includes(code))
      .map(({ native }) => native)
      .join(", ");
  const standard = byLanguage.map(({ code }) => code).filter((code) => !edited.has(code));
  return (
    <section className="space-y-4 rounded-xl border p-4" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`} className="font-semibold">
        {n(`channels.${channel}`)}
      </h3>
      {editable && edited.size > 0 && standard.length > 0 ? (
        <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
          {t("partlyEdited", { edited: names([...edited]), standard: names(standard) })}
        </p>
      ) : null}
      <div
        className={cn(
          "grid gap-6",
          byLanguage.length === 2 && "lg:grid-cols-2",
          byLanguage.length >= 3 && "lg:grid-cols-3",
        )}
      >
        {byLanguage.map(({ code, native, text }) => (
          <TextEditor
            key={`${code}-${text.source}-${text.subject}-${text.body}`}
            event={event}
            locale={code}
            language={native}
            text={text}
          />
        ))}
      </div>
    </section>
  );
}

/** Settings → Messages → Message texts: the words of each message, in every language the
 * distributor's people may use, side by side. */
export function NotificationTextsPage() {
  const t = useTranslations("notifyAdmin.texts");
  const n = useTranslations("notifications");
  const { me } = useAuth();
  const events = useNotificationRules().data?.data.events ?? [];
  const [event, setEvent] = useState("order.accepted");
  const shown = me?.languages?.length ? me.languages : [{ code: "en", native: "English" }];
  const queries = useQueries({
    queries: shown.map(({ code }) => getNotificationTextsQueryOptions(event, { locale: code })),
  });
  const loading = queries.some((q) => q.isLoading);
  const failed = queries.find((q) => q.error);
  const english = queries[0]?.data?.data ?? [];
  const textIn = (index: number, audience: string, channel: string) =>
    queries[index]?.data?.data.find((x) => x.audience === audience && x.channel === channel);
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <NotificationsNav />
      <div className="mb-6 max-w-md space-y-1">
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
      {loading ? (
        <CardSkeleton />
      ) : failed ? (
        <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => void q.refetch())} />
      ) : !english.length ? (
        <EmptyState title={t("empty")} />
      ) : (
        <div className="space-y-8">
          {AUDIENCES.filter((audience) => english.some((text) => text.audience === audience)).map(
            (audience) => (
              <section key={audience} className="space-y-4" aria-labelledby={`to-${audience}`}>
                <div className="space-y-1">
                  <h2 id={`to-${audience}`} className="text-lg font-semibold">
                    {t(`audiences.${audience}`)}
                  </h2>
                  <p className="text-muted-foreground text-sm">{t(`audienceHints.${audience}`)}</p>
                </div>
                {english
                  .filter((text) => text.audience === audience)
                  .map((text) => (
                    <MessageTexts
                      key={`${event}-${audience}-${text.channel}`}
                      event={event}
                      audience={audience}
                      channel={text.channel}
                      byLanguage={shown
                        .map(({ code, native }, index) => ({
                          code,
                          native,
                          text: textIn(index, audience, text.channel),
                        }))
                        .filter((row): row is { code: string; native: string; text: Text } =>
                          Boolean(row.text),
                        )}
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
