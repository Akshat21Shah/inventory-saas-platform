"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Lock, MoonStar, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ErrorState } from "@/components/shared/error-state";
import { FormSelect } from "@/components/shared/form-select";
import { PageHeader } from "@/components/shared/page-header";
import { TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  getNotificationRulesQueryKey,
  notificationRulesReset,
  notificationRulesUpdate,
  useNotificationRules,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type {
  EventRules,
  NotificationChannelEnum,
  NotificationRecipientEnum,
  PermissionChoice,
  Rule,
  RulesMatrix,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney } from "@/lib/format";

import { eventKey, NotificationsNav } from "./nav";

const RECIPIENTS: NotificationRecipientEnum[] = [
  "SHOP",
  "SALESPERSON",
  "COLLECTOR",
  "STAFF_PERMISSION",
  "OWNERS",
];

/** Whether this recipient's WhatsApp text can be sent (approved, or no approval needed). */
function whatsappReady(event: EventRules, recipient: NotificationRecipientEnum): boolean {
  const audience = recipient === "SHOP" ? "SHOP" : "STAFF";
  return event.whatsapp.templates.find((a) => a.audience === audience)?.ready ?? true;
}

/** Rules already sending WhatsApp with a template the provider hasn't approved (none are sent). */
function waitingForApproval(event: EventRules): boolean {
  return event.rules.some(
    (rule) =>
      rule.enabled !== false &&
      rule.channels.includes("WHATSAPP") &&
      !whatsappReady(event, rule.recipient),
  );
}

interface Draft {
  recipient: NotificationRecipientEnum;
  permission: string;
  channels: NotificationChannelEnum[];
  enabled: boolean;
  compulsory: boolean;
}

function RuleSummary({ rule, permissions }: { rule: Rule; permissions: PermissionChoice[] }) {
  const t = useTranslations("notifyAdmin");
  const n = useTranslations("notifications");
  const who =
    rule.recipient === "STAFF_PERMISSION"
      ? (permissions.find((p) => p.code === rule.permission)?.description ?? rule.permission)
      : t(`recipients.${rule.recipient}`);
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      <span className={rule.enabled ? "font-medium" : "text-muted-foreground line-through"}>
        {who}
      </span>
      <span className="text-muted-foreground">
        {rule.enabled ? rule.channels.map((c) => n(`channels.${c}`)).join(", ") : t("rules.off")}
      </span>
      {rule.compulsory && rule.enabled ? (
        <span className="bg-muted inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs">
          <Lock aria-hidden className="size-3" />
          {t("rules.compulsory")}
        </span>
      ) : null}
    </li>
  );
}

function RuleEditor({
  event,
  matrix,
  onClose,
}: {
  event: EventRules;
  matrix: RulesMatrix;
  onClose: () => void;
}) {
  const t = useTranslations("notifyAdmin");
  const n = useTranslations("notifications");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    event.rules.map((r) => ({
      recipient: r.recipient,
      permission: r.permission ?? "",
      channels: [...r.channels],
      enabled: r.enabled ?? true,
      compulsory: r.compulsory ?? false,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label = n(`events.${eventKey(event.code)}`);
  const recipients = RECIPIENTS.filter((r) => r !== "SHOP" || event.shop_facing);
  const update = (index: number, change: Partial<Draft>) =>
    setDrafts((current) => current.map((d, i) => (i === index ? { ...d, ...change } : d)));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await notificationRulesUpdate(event.code, {
        rules: drafts.map((d) => ({
          recipient: d.recipient,
          permission: d.recipient === "STAFF_PERMISSION" ? d.permission : "",
          channels: d.channels,
          enabled: d.enabled,
          compulsory: d.recipient === "SHOP" && d.compulsory,
        })),
      });
      await client.invalidateQueries({ queryKey: getNotificationRulesQueryKey() });
      toast.success(t("rules.saved"));
      onClose();
    } catch (thrown) {
      const byField = fields(thrown);
      setError(Object.values(byField)[0] ?? message(thrown));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>{t("rules.editBody")}</DialogDescription>
        </DialogHeader>
        <ul className="space-y-4">
          {drafts.map((draft, index) => {
            const allowed = (matrix.recipients[draft.recipient] ?? []) as NotificationChannelEnum[];
            const rowLabel = t(`recipients.${draft.recipient}`);
            const ready = whatsappReady(event, draft.recipient);
            const inForce = event.rules.some(
              (r) =>
                r.recipient === draft.recipient &&
                (r.permission ?? "") === draft.permission &&
                r.channels.includes("WHATSAPP"),
            );
            return (
              <li key={index} className="space-y-3 rounded-xl border p-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <span className="text-muted-foreground text-xs">{t("rules.recipient")}</span>
                    <FormSelect
                      value={draft.recipient}
                      onValueChange={(value) =>
                        update(index, {
                          recipient: value as NotificationRecipientEnum,
                          channels: draft.channels.filter((c) =>
                            (matrix.recipients[value] ?? []).includes(c),
                          ),
                          compulsory: value === "SHOP" && draft.compulsory,
                        })
                      }
                      options={recipients.map((r) => ({
                        value: r,
                        label: t(`recipients.${r}`),
                      }))}
                    />
                  </div>
                  {draft.recipient === "STAFF_PERMISSION" ? (
                    <div className="space-y-1">
                      <span className="text-muted-foreground text-xs">{t("rules.permission")}</span>
                      <FormSelect
                        value={draft.permission}
                        placeholder={t("rules.choosePermission")}
                        onValueChange={(value) => update(index, { permission: value })}
                        options={matrix.permissions.map((p) => ({
                          value: p.code,
                          label: p.description,
                        }))}
                      />
                    </div>
                  ) : null}
                </div>
                <fieldset>
                  <legend className="text-muted-foreground mb-1 text-xs">
                    {t("rules.channels")}
                  </legend>
                  <div className="flex flex-wrap gap-x-5">
                    {allowed.map((channel) => (
                      <label key={channel} className="flex min-h-11 items-center gap-2 text-sm">
                        <Checkbox
                          disabled={
                            channel === "WHATSAPP" &&
                            !ready &&
                            !inForce &&
                            !draft.channels.includes(channel)
                          }
                          checked={draft.channels.includes(channel)}
                          onCheckedChange={(checked) =>
                            update(index, {
                              channels: checked
                                ? [...draft.channels, channel]
                                : draft.channels.filter((c) => c !== channel),
                            })
                          }
                        />
                        {n(`channels.${channel}`)}
                      </label>
                    ))}
                  </div>
                  {!ready && allowed.includes("WHATSAPP") ? (
                    <p
                      className={
                        draft.channels.includes("WHATSAPP")
                          ? "bg-warning/15 flex gap-2 rounded-lg p-2 text-xs"
                          : "text-muted-foreground text-xs"
                      }
                    >
                      {draft.channels.includes("WHATSAPP") ? (
                        <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                      ) : null}
                      {t(
                        draft.channels.includes("WHATSAPP")
                          ? "rules.whatsappNotApproved"
                          : "rules.whatsappAfterApproval",
                      )}
                    </p>
                  ) : null}
                </fieldset>
                <div className="flex flex-wrap items-center gap-x-6">
                  <label className="flex min-h-11 items-center gap-2 text-sm">
                    <Switch
                      checked={draft.enabled}
                      onCheckedChange={(enabled) => update(index, { enabled })}
                      aria-label={`${rowLabel}: ${t("rules.enabled")}`}
                    />
                    {t("rules.enabled")}
                  </label>
                  {draft.recipient === "SHOP" ? (
                    <label className="flex min-h-11 items-center gap-2 text-sm">
                      <Switch
                        checked={draft.compulsory}
                        onCheckedChange={(compulsory) => update(index, { compulsory })}
                        aria-label={t("rules.compulsoryLabel")}
                      />
                      {t("rules.compulsoryLabel")}
                    </label>
                  ) : null}
                  <Button
                    variant="ghost"
                    className="text-destructive ml-auto min-h-11"
                    onClick={() => setDrafts((current) => current.filter((_, i) => i !== index))}
                  >
                    <Trash2 aria-hidden />
                    {t("rules.remove")}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() =>
            setDrafts((current) => [
              ...current,
              {
                recipient: "STAFF_PERMISSION",
                permission: "",
                channels: ["IN_APP"],
                enabled: true,
                compulsory: false,
              },
            ])
          }
        >
          <Plus aria-hidden />
          {t("rules.add")}
        </Button>
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <DialogFooter className="gap-2">
          <ConfirmDialog
            trigger={
              <Button variant="ghost" className="min-h-11 sm:mr-auto" disabled={!event.customised}>
                {t("rules.reset")}
              </Button>
            }
            title={t("rules.resetConfirm")}
            onConfirm={async () => {
              await notificationRulesReset(event.code);
              await client.invalidateQueries({ queryKey: getNotificationRulesQueryKey() });
              toast.success(t("rules.resetDone"));
              onClose();
            }}
          />
          <Button className="min-h-11" disabled={busy} onClick={() => void save()}>
            {t("rules.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Estimate({ event }: { event: EventRules }) {
  const t = useTranslations("notifyAdmin.rules");
  const wa = event.whatsapp;
  if (!wa.enabled || !wa.messages_30_days) return null;
  return (
    <p className="text-muted-foreground text-xs">
      {wa.cost_30_days
        ? t("estimateCost", { count: wa.messages_30_days, amount: formatMoney(wa.cost_30_days) })
        : t("estimate", { count: wa.messages_30_days })}
    </p>
  );
}

/** Settings → Messages → Who gets what: every message with its recipients and channels, what
 * WhatsApp would cost, and an editor per message. */
export function NotificationRulesPage() {
  const t = useTranslations("notifyAdmin");
  const n = useTranslations("notifications");
  const query = useNotificationRules();
  const matrix = query.data?.data;
  const [editing, setEditing] = useState<string | null>(null);
  const groups = matrix ? [...new Set(matrix.events.map((e) => e.group))] : [];
  const totalMessages =
    matrix?.events.reduce(
      (sum, e) => sum + (e.whatsapp.enabled ? e.whatsapp.messages_30_days : 0),
      0,
    ) ?? 0;
  const editingEvent = matrix?.events.find((e) => e.code === editing);
  return (
    <>
      <PageHeader title={t("rules.title")} description={t("rules.description")} />
      <NotificationsNav />
      {query.isLoading ? (
        <TableSkeleton columns={3} />
      ) : query.error || !matrix ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-6">
          <div className="bg-muted/40 space-y-1 rounded-xl border p-4 text-sm">
            {!matrix.whatsapp_feature_enabled ? <p>{t("rules.whatsappOff")}</p> : null}
            <p>{t("rules.optedIn", { opted: matrix.shops.opted_in, shops: matrix.shops.shops })}</p>
            <p>
              {matrix.whatsapp_cost_30_days
                ? t("rules.cost", { amount: formatMoney(matrix.whatsapp_cost_30_days) })
                : t("rules.costCountsOnly", { count: totalMessages })}
            </p>
          </div>
          {groups.map((group) => (
            <section key={group} aria-labelledby={`rules-${group}`} className="space-y-2">
              <h2 id={`rules-${group}`} className="text-lg font-semibold">
                {n(`groups.${group}`)}
              </h2>
              <ul className="divide-y rounded-xl border">
                {matrix.events
                  .filter((e) => e.group === group)
                  .map((event) => (
                    <li
                      key={event.code}
                      className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start"
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <p className="flex flex-wrap items-center gap-2 font-medium">
                          {n(`events.${eventKey(event.code)}`)}
                          {event.customised ? (
                            <span className="bg-brand-50 text-brand-800 rounded-full px-2 py-0.5 text-xs">
                              {t("rules.changed")}
                            </span>
                          ) : null}
                          {!event.urgent ? (
                            <span className="text-muted-foreground inline-flex items-center gap-1 text-xs font-normal">
                              <MoonStar aria-hidden className="size-3" />
                              {t("rules.notUrgent")}
                            </span>
                          ) : null}
                        </p>
                        {event.rules.length ? (
                          <ul className="space-y-1">
                            {event.rules.map((rule) => (
                              <RuleSummary
                                key={`${rule.recipient}-${rule.permission}`}
                                rule={rule}
                                permissions={matrix.permissions}
                              />
                            ))}
                          </ul>
                        ) : (
                          <p className="text-muted-foreground text-sm">{t("rules.nobody")}</p>
                        )}
                        <Estimate event={event} />
                        {waitingForApproval(event) ? (
                          <p className="text-warning-strong flex items-center gap-1 text-xs">
                            <AlertTriangle aria-hidden className="size-3.5 shrink-0" />
                            {t("rules.whatsappWaiting")}
                          </p>
                        ) : null}
                      </div>
                      <Button
                        variant="outline"
                        className="min-h-11 shrink-0"
                        onClick={() => setEditing(event.code)}
                        aria-label={`${t("rules.edit")}: ${n(`events.${eventKey(event.code)}`)}`}
                      >
                        {t("rules.edit")}
                      </Button>
                    </li>
                  ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      {editingEvent && matrix ? (
        <RuleEditor event={editingEvent} matrix={matrix} onClose={() => setEditing(null)} />
      ) : null}
    </>
  );
}
