"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FilterSelect } from "@/components/catalog/controls";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  notificationDeliveryRetry,
  useNotificationDeliveries,
  useNotificationDelivery,
  useNotificationDeliveryCounts,
  useNotificationRules,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type {
  DeliveryRow,
  NotificationDeliveriesChannel,
  NotificationDeliveriesStatus,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { formatDateTime } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { useErrorText } from "@/lib/api/use-error-text";

import { eventKey, NotificationsNav } from "./nav";
import { ProviderMessage } from "@/components/shared/provider-message";

const ALL = "all";
const STATUSES = ["FAILED", "PENDING", "SENDING", "SENT", "SKIPPED"] as const;
const CHANNELS = ["IN_APP", "EMAIL", "WHATSAPP", "SMS"] as const;

function refreshDeliveries(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({
    predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/v1/notification-deliveries"),
  });
}

function DeliveryDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useTranslations("notifyAdmin");
  const n = useTranslations("notifications");
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useNotificationDelivery(id);
  const row = query.data?.data;
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{row ? row.title : t("deliveries.details")}</DialogTitle>
          <DialogDescription>
            {row
              ? `${n(`events.${eventKey(row.event_code)}`)} · ${n(`channels.${row.channel}`)}`
              : ""}
          </DialogDescription>
        </DialogHeader>
        {query.isLoading ? (
          <CardSkeleton />
        ) : query.error || !row ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={row.status ?? ""} labels="deliveryStatus" />
              {row.skip_reason ? (
                <span className="text-muted-foreground">{t(`skip.${row.skip_reason}`)}</span>
              ) : null}
            </div>
            <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1">
              <dt className="text-muted-foreground">{t("deliveries.to")}</dt>
              <dd className="break-words">
                {[row.recipient_name, row.shop_name, row.address].filter(Boolean).join(" · ")}
              </dd>
              <dt className="text-muted-foreground">{t("deliveries.when")}</dt>
              <dd>
                <DateText value={row.created_at} withTime />
              </dd>
            </dl>
            {row.send_after && row.status === "PENDING" ? (
              <p className="text-muted-foreground">
                {t("deliveries.sendAfter", { time: formatDateTime(row.send_after) })}
              </p>
            ) : null}
            <p className="bg-muted/40 rounded-lg p-3 break-words whitespace-pre-line">{row.body}</p>
            <section className="space-y-2">
              <h3 className="font-semibold">{t("deliveries.attempts")}</h3>
              {row.delivery_attempts.length ? (
                <ol className="divide-y rounded-lg border">
                  {row.delivery_attempts.map((attempt) => (
                    <li key={attempt.attempt_no} className="space-y-1 p-3">
                      <p className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">
                          {t("deliveries.attempt", { number: attempt.attempt_no })}
                        </span>
                        <StatusBadge status={attempt.status} labels="deliveryStatus" />
                        <span className="text-muted-foreground text-xs">
                          <DateText value={attempt.created_at} withTime />
                        </span>
                      </p>
                      {attempt.error ? (
                        <p className="text-destructive text-xs break-words">{attempt.error}</p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-muted-foreground">{t("deliveries.noAttempts")}</p>
              )}
            </section>
            {row.status === "FAILED" ? (
              <Button
                className="min-h-11"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await notificationDeliveryRetry(row.id);
                    toast.success(t("deliveries.retried"));
                    refreshDeliveries(client);
                  } catch (thrown) {
                    toast.error(message(thrown));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <RotateCcw aria-hidden />
                {t("deliveries.retry")}
              </Button>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Settings → Messages → Delivery log: every message and what happened to it. */
export function DeliveriesPage() {
  const t = useTranslations("notifyAdmin");
  const n = useTranslations("notifications");
  const tp = useTranslations("providerMessages");
  const cursor = useCursor();
  const [status, setStatus] = useState<string>(ALL);
  const [channel, setChannel] = useState<string>(ALL);
  const [event, setEvent] = useState<string>(ALL);
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search, 300);
  const [open, setOpen] = useState<string | null>(null);
  const events = useNotificationRules().data?.data.events ?? [];
  const counts = useNotificationDeliveryCounts().data?.data;
  const query = useNotificationDeliveries({
    cursor: cursor.cursor,
    ...(status !== ALL ? { status: status as NotificationDeliveriesStatus } : {}),
    ...(channel !== ALL ? { channel: channel as NotificationDeliveriesChannel } : {}),
    ...(event !== ALL ? { event } : {}),
    ...(debounced ? { search: debounced } : {}),
  });
  const page = query.data?.data;
  const active = [status, channel, event].filter((v) => v !== ALL).length;
  const columns: DataTableColumn<DeliveryRow>[] = [
    {
      id: "title",
      header: t("deliveries.event"),
      cell: ({ row }) => (
        <span className="block max-w-64 min-w-0 whitespace-normal">
          <span className="block font-medium break-words">{row.original.title}</span>
          <span className="text-muted-foreground block text-xs">
            {n(`events.${eventKey(row.original.event_code)}`)}
          </span>
        </span>
      ),
    },
    {
      id: "to",
      header: t("deliveries.to"),
      cell: ({ row }) => (
        <span className="block max-w-56 break-words whitespace-normal">
          {[row.original.recipient_name, row.original.shop_name].filter(Boolean).join(" · ")}
        </span>
      ),
    },
    {
      id: "status",
      header: t("deliveries.status"),
      cell: ({ row }) => (
        <span className="block max-w-56 space-y-1 whitespace-normal">
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={row.original.status ?? ""} labels="deliveryStatus" />
            <span className="text-muted-foreground text-xs">
              {n(`channels.${row.original.channel}`)}
            </span>
          </span>
          {row.original.skip_reason ? (
            <span className="text-muted-foreground block text-xs">
              {t(`skip.${row.original.skip_reason}`)}
            </span>
          ) : null}
          {row.original.status === "FAILED" && row.original.last_error ? (
            <ProviderMessage
              line={tp("sending")}
              message={row.original.last_error}
              compact
              className="text-destructive text-xs"
            />
          ) : null}
        </span>
      ),
    },
    {
      id: "when",
      header: t("deliveries.when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="outline"
          className="min-h-10 max-md:min-h-11"
          onClick={() => setOpen(row.original.id)}
          aria-label={`${t("deliveries.details")}: ${row.original.title}`}
        >
          {row.original.status === "FAILED" ? t("deliveries.retry") : t("deliveries.details")}
        </Button>
      ),
    },
  ];
  return (
    <>
      <PageHeader title={t("deliveries.title")} description={t("deliveries.description")} />
      <NotificationsNav />
      {counts ? (
        <p className="text-muted-foreground mb-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <span>{t("deliveries.last7")}:</span>
          {STATUSES.map((s) => (
            <span key={s} className={s === "FAILED" && counts.FAILED ? "text-destructive" : ""}>
              {t(`deliveryStatus.${s}`)} {counts[s]}
            </span>
          ))}
        </p>
      ) : null}
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("deliveries.title")}
        empty={{ title: t("deliveries.empty"), description: t("deliveries.emptyBody") }}
        cardLayout={{
          title: "title",
          to: "primary",
          status: "primary",
          when: "secondary",
          actions: "actions",
        }}
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              setStatus(ALL);
              setChannel(ALL);
              setEvent(ALL);
              setSearch("");
              cursor.reset();
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  cursor.reset();
                }}
                placeholder={t("deliveries.searchPlaceholder")}
                aria-label={t("deliveries.search")}
                className="min-h-10"
              />
            }
            filters={
              <>
                <FilterSelect
                  label={t("deliveries.status")}
                  value={status}
                  onChange={(value) => {
                    setStatus(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("deliveries.allStatuses") },
                    ...STATUSES.map((s) => ({ value: s, label: t(`deliveryStatus.${s}`) })),
                  ]}
                />
                <FilterSelect
                  label={t("deliveries.channel")}
                  value={channel}
                  onChange={(value) => {
                    setChannel(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("deliveries.allChannels") },
                    ...CHANNELS.map((c) => ({ value: c, label: n(`channels.${c}`) })),
                  ]}
                />
                <FilterSelect
                  label={t("deliveries.event")}
                  value={event}
                  onChange={(value) => {
                    setEvent(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("deliveries.allEvents") },
                    ...events.map((e) => ({
                      value: e.code,
                      label: n(`events.${eventKey(e.code)}`),
                    })),
                  ]}
                />
              </>
            }
          />
        }
      />
      {open ? <DeliveryDialog id={open} onClose={() => setOpen(null)} /> : null}
    </>
  );
}
