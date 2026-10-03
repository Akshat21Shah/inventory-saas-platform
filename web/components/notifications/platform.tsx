"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ProviderMessage } from "@/components/shared/provider-message";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { SubNav } from "@/components/shared/sub-nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  getPlatformNotificationTemplatesQueryKey,
  platformNotificationFailureRetry,
  platformNotificationTemplateApproval,
  platformNotificationTemplateUpdate,
  platformNotificationTextPreview,
  usePlatformNotificationFailures,
  usePlatformNotificationTemplates,
} from "@/lib/api/generated/endpoints/platform/platform";
import {
  TemplateApprovalStatusEnum,
  type PlatformFailure,
  type PlatformTemplate,
  type PlatformTextInputRequest,
  type TextPreview,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { languages, locales } from "@/lib/i18n/config";
import { cn } from "@/lib/utils";

import { eventKey } from "./manage/nav";

function PlatformNav() {
  const t = useTranslations("platformMessages.nav");
  return (
    <SubNav
      label={t("label")}
      items={[
        { href: "/platform/notifications", label: t("texts") },
        { href: "/platform/notifications/failures", label: t("failures") },
      ]}
    />
  );
}

/** Where a WhatsApp template stands with the provider (ADR-049 item 12): the super admin records
 * each answer. A real provider sends only approved templates; editing an approved text sends it
 * back to "Not submitted". */
function ApprovalControls({ row }: { row: PlatformTemplate }) {
  const t = useTranslations("platformMessages.texts.approval");
  const statuses = useTranslations("approvalStatus");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [status, setStatus] = useState<TemplateApprovalStatusEnum>(row.approval_status);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = `${row.id}-approval`;

  const record = async () => {
    setBusy(true);
    setError(null);
    try {
      await platformNotificationTemplateApproval(row.id, { status, note: note.trim() });
      await client.invalidateQueries({ queryKey: getPlatformNotificationTemplatesQueryKey() });
      toast.success(t("recorded"));
    } catch (thrown) {
      const byField = fields(thrown);
      setError(Object.values(byField)[0] ?? message(thrown));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-muted/40 space-y-3 rounded-lg border p-3" aria-labelledby={`${id}-h`}>
      <p id={`${id}-h`} className="flex flex-wrap items-center gap-2 text-sm font-medium">
        {t("title")}
        <StatusBadge status={row.approval_status} labels="approvalStatus" />
        {row.approval_changed_at ? (
          <span className="text-muted-foreground text-xs font-normal">
            <DateText value={row.approval_changed_at} withTime />
          </span>
        ) : null}
      </p>
      {row.approval_note ? <p className="text-sm">{row.approval_note}</p> : null}
      {row.approval_status === "APPROVED" ? (
        <p className="text-muted-foreground text-xs">{t("editResets")}</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
        <div className="space-y-1">
          <Label htmlFor={`${id}-status`}>{t("status")}</Label>
          <FormSelect
            id={`${id}-status`}
            value={status}
            onValueChange={(value) => setStatus(value as TemplateApprovalStatusEnum)}
            options={Object.values(TemplateApprovalStatusEnum).map((value) => ({
              value,
              label: statuses(value),
            }))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-note`}>
            {status === "REJECTED" ? t("reasonRequired") : t("note")}
          </Label>
          <Input
            id={`${id}-note`}
            maxLength={300}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="min-h-10"
          />
        </div>
        <Button
          variant="outline"
          className="min-h-11"
          disabled={busy || (status === row.approval_status && !note.trim())}
          onClick={() => void record()}
        >
          {t("record")}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function PlatformTextEditor({ row }: { row: PlatformTemplate }) {
  const t = useTranslations("platformMessages.texts");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [subject, setSubject] = useState(row.subject);
  const [body, setBody] = useState(row.body);
  const [name, setName] = useState(row.whatsapp_template_name ?? "");
  const [category, setCategory] = useState<string>(row.whatsapp_category ?? "");
  const [preview, setPreview] = useState<TextPreview | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const whatsapp = row.channel === "WHATSAPP";
  const id = `${row.event_code}-${row.audience}-${row.channel}-${row.locale}`;
  const input = { audience: row.audience, locale: row.locale as "en", subject, body };

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
    <section className="min-w-0 space-y-3" aria-labelledby={`${id}-h`} lang={row.locale}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`${id}-h`} className="font-medium">
          {languages.find((l) => l.code === row.locale)?.native ?? row.locale}
        </h3>
        {row.submitted_by_default === true ? (
          <span className="bg-success/12 text-success-strong rounded-full px-2 py-0.5 text-xs">
            {t("firstBatch")}
          </span>
        ) : row.submitted_by_default === false ? (
          <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-xs">
            {t("optional")}
          </span>
        ) : null}
      </div>
      {row.channel === "IN_APP" || row.channel === "EMAIL" ? (
        <div className="space-y-1">
          <Label htmlFor={`${id}-subject`}>{t("subject")}</Label>
          <Input
            id={`${id}-subject`}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="min-h-10"
          />
          {errors.subject ? <p className="text-destructive text-sm">{errors.subject}</p> : null}
        </div>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor={`${id}-body`}>{t("body")}</Label>
        <Textarea
          id={`${id}-body`}
          rows={3}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        {errors.body ? <p className="text-destructive text-sm">{errors.body}</p> : null}
      </div>
      {whatsapp ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor={`${id}-name`}>{t("templateName")}</Label>
            <Input
              id={`${id}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="min-h-10 font-mono"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${id}-category`}>{t("category")}</Label>
            <FormSelect
              id={`${id}-category`}
              value={category}
              onValueChange={setCategory}
              options={["UTILITY", "MARKETING", "AUTHENTICATION"].map((value) => ({
                value,
                label: t(`categories.${value}`),
              }))}
            />
          </div>
          <p className="text-muted-foreground text-xs sm:col-span-2">
            {t("parameters", { names: (row.variables as string[]).join(", ") })}
          </p>
          <div className="sm:col-span-2">
            <ApprovalControls row={row} />
          </div>
        </div>
      ) : null}
      {preview ? (
        <div className="bg-brand-50 space-y-1 rounded-lg p-3 text-sm" aria-live="polite">
          {preview.subject ? <p className="font-medium">{preview.subject}</p> : null}
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
              const shown = await platformNotificationTextPreview({
                event: row.event_code,
                channel: row.channel,
                ...input,
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
              await platformNotificationTemplateUpdate(row.event_code, row.channel, {
                ...input,
                ...(whatsapp
                  ? {
                      whatsapp_template_name: name,
                      whatsapp_category: category as PlatformTextInputRequest["whatsapp_category"],
                    }
                  : {}),
              });
              await client.invalidateQueries({
                queryKey: getPlatformNotificationTemplatesQueryKey(),
              });
            }, t("saved"))
          }
        >
          {t("save")}
        </Button>
      </div>
    </section>
  );
}

/** Super admin → Messages: the platform's default texts, incl. the approved WhatsApp templates. */
export function PlatformTextsPage() {
  const t = useTranslations("platformMessages.texts");
  const n = useTranslations("notifications");
  const [event, setEvent] = useState("order.accepted");
  const query = usePlatformNotificationTemplates();
  const all = query.data?.data ?? [];
  const events = [...new Set(all.map((row) => row.event_code))];
  const rows = all.filter((row) => row.event_code === event);
  const whatsapp = all.filter((row) => row.channel === "WHATSAPP");
  const counts = Object.values(TemplateApprovalStatusEnum)
    .map((status) => ({
      status,
      count: whatsapp.filter((r) => r.approval_status === status).length,
    }))
    .filter((c) => c.count > 0);
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PlatformNav />
      {counts.length ? (
        <p
          className="mb-4 flex flex-wrap items-center gap-2 text-sm"
          aria-label={t("approval.summary")}
        >
          <span className="text-muted-foreground">{t("approval.summary")}</span>
          {counts.map(({ status, count }) => (
            <span key={status} className="inline-flex items-center gap-1">
              <StatusBadge status={status} labels="approvalStatus" />
              <span className="tabular-nums">{count}</span>
            </span>
          ))}
        </p>
      ) : null}
      <div className="mb-6 max-w-md space-y-1">
        <Label htmlFor="platform-event">{t("event")}</Label>
        <FormSelect
          id="platform-event"
          value={event}
          onValueChange={setEvent}
          options={(events.length ? events : [event]).map((code) => {
            const waiting = whatsapp.some(
              (r) => r.event_code === code && r.approval_status !== "APPROVED",
            );
            const label = n(`events.${eventKey(code)}`);
            return { value: code, label: waiting ? `${label} · ${t("approval.waiting")}` : label };
          })}
        />
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !rows.length ? (
        <EmptyState title={t("empty")} />
      ) : (
        <div className="space-y-4">
          {[...new Set(rows.map((row) => `${row.audience}|${row.channel}`))].map((group) => {
            const [audience, channel] = group.split("|");
            const inGroup = rows
              .filter((row) => row.audience === audience && row.channel === channel)
              .sort((a, b) => locales.indexOf(a.locale) - locales.indexOf(b.locale));
            return (
              <section
                key={group}
                className="space-y-4 rounded-xl border p-4"
                aria-labelledby={`group-${group}`}
              >
                <h2 id={`group-${group}`} className="font-semibold">
                  {t(`audiences.${audience}`)} · {n(`channels.${channel}`)}
                </h2>
                <div
                  className={cn(
                    "grid gap-6",
                    inGroup.length === 2 && "lg:grid-cols-2",
                    inGroup.length >= 3 && "lg:grid-cols-3",
                  )}
                >
                  {inGroup.map((row) => (
                    <PlatformTextEditor key={`${row.id}-${row.updated_at}`} row={row} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}

/** Super admin → Messages → Failures: failed messages of every business, with retry. */
export function PlatformFailuresPage() {
  const t = useTranslations("platformMessages.failures");
  const n = useTranslations("notifications");
  const tp = useTranslations("providerMessages");
  const client = useQueryClient();
  const { message } = useErrorText();
  const cursor = useCursor();
  const query = usePlatformNotificationFailures({ cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<PlatformFailure>[] = [
    {
      id: "title",
      header: t("message"),
      cell: ({ row }) => (
        <span className="block max-w-64 whitespace-normal">
          <span className="block font-medium break-words">{row.original.title}</span>
          <span className="text-muted-foreground block text-xs">
            {n(`events.${eventKey(row.original.event_code)}`)} ·{" "}
            {n(`channels.${row.original.channel}`)}
          </span>
        </span>
      ),
    },
    { id: "tenant", header: t("business"), cell: ({ row }) => row.original.tenant_name },
    {
      id: "error",
      header: t("error"),
      cell: ({ row }) => (
        <ProviderMessage
          line={tp("sending")}
          message={row.original.last_error}
          compact
          className="text-destructive max-w-56 text-xs whitespace-normal"
        />
      ),
    },
    {
      id: "when",
      header: t("when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="outline"
          className="min-h-10 max-md:min-h-11"
          aria-label={`${t("retry")}: ${row.original.title}`}
          onClick={async () => {
            try {
              await platformNotificationFailureRetry(row.original.id);
              toast.success(t("retried"));
              void client.invalidateQueries({
                predicate: (q) =>
                  String(q.queryKey[0] ?? "").startsWith("/api/v1/platform/notification-failures"),
              });
            } catch (thrown) {
              toast.error(message(thrown));
            }
          }}
        >
          <RotateCcw aria-hidden />
          {t("retry")}
        </Button>
      ),
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <PlatformNav />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          title: "title",
          tenant: "primary",
          error: "primary",
          when: "secondary",
          actions: "actions",
        }}
      />
    </>
  );
}
