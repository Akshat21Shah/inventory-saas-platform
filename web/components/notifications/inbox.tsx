"use client";

import { useQueryClient } from "@tanstack/react-query";
import { BellOff, CheckCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { InboxItem } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

import { INBOX, type InboxScope, refreshNotifications } from "./scope";

function InboxSkeleton() {
  return (
    <ul className="divide-y rounded-xl border" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="space-y-2 p-4">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-5/6" />
        </li>
      ))}
    </ul>
  );
}

/** The person's messages, newest first: unread ones stand out; opening one marks it read and
 * goes to its page (an order, a bill, a payment). */
export function NotificationInbox({ scope }: { scope: InboxScope }) {
  const t = useTranslations("notifications");
  const client = useQueryClient();
  const router = useRouter();
  const inbox = INBOX[scope];
  const [show, setShow] = useState<"all" | "unread">("all");
  const cursor = useCursor();
  const list = inbox.useList({
    cursor: cursor.cursor,
    ...(show === "unread" ? { unread: true } : {}),
  });
  const unread = inbox.useUnread().data?.data.unread ?? 0;
  const [busy, setBusy] = useState(false);
  const page = list.data?.data;
  const pager = cursor.pagination(page);

  const open = async (item: InboxItem) => {
    if (!item.is_read) {
      await inbox.markRead(item.id).catch(() => undefined);
      refreshNotifications(client);
    }
    if (item.path) router.push(item.path);
  };

  const readAll = async () => {
    setBusy(true);
    try {
      await inbox.markAllRead();
      refreshNotifications(client);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("title")}
        description={unread ? t("unreadCount", { count: unread }) : t("allRead")}
        actions={
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!unread || busy}
            onClick={() => void readAll()}
          >
            <CheckCheck aria-hidden />
            {t("markAllRead")}
          </Button>
        }
      />
      <Tabs
        value={show}
        onValueChange={(value) => {
          setShow(value as "all" | "unread");
          cursor.reset();
        }}
      >
        <TabsList>
          <TabsTrigger value="all">{t("all")}</TabsTrigger>
          <TabsTrigger value="unread">{t("unread")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {list.isPending ? (
        <InboxSkeleton />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !page?.results.length ? (
        <EmptyState
          icon={BellOff}
          title={show === "unread" ? t("emptyUnread") : t("empty")}
          description={t("emptyBody")}
        />
      ) : (
        <ul className="divide-y rounded-xl border">
          {page.results.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => void open(item)}
                className={cn(
                  "hover:bg-muted/60 flex min-h-11 w-full gap-3 p-4 text-left",
                  !item.is_read && "bg-brand-50/60",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    item.is_read ? "bg-transparent" : "bg-brand-600",
                  )}
                />
                <span className="min-w-0 flex-1 space-y-1">
                  <span className={cn("block break-words", !item.is_read && "font-semibold")}>
                    {item.title}
                    {!item.is_read ? <span className="sr-only"> ({t("unread")})</span> : null}
                  </span>
                  <span className="text-muted-foreground block text-sm break-words">
                    {item.body}
                  </span>
                  <span className="text-muted-foreground block text-xs">
                    <DateText value={item.created_at} withTime />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {pager ? (
        <div className="flex justify-between">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!pager.hasPrevious}
            onClick={pager.onPrevious}
          >
            {t("newer")}
          </Button>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!pager.hasNext}
            onClick={pager.onNext}
          >
            {t("older")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
