"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAuth } from "@/components/auth/auth-provider";
import { cn } from "@/lib/utils";

import { INBOX, type InboxScope } from "./scope";

/** The bell with the unread count; opens the inbox. Refreshed every minute and when the live
 * socket says a message arrived. `tone="onPrimary"` for the shop's coloured header. */
export function NotificationBell({
  scope,
  tone = "default",
}: {
  scope: InboxScope;
  tone?: "default" | "onPrimary";
}) {
  const t = useTranslations("notifications");
  const { me } = useAuth();
  const inbox = INBOX[scope];
  const unread =
    inbox.useUnread({ query: { enabled: Boolean(me), refetchInterval: 60_000 } }).data?.data
      .unread ?? 0;
  const label = unread ? t("bellUnread", { count: unread }) : t("bell");
  return (
    <Link
      href={inbox.href}
      aria-label={label}
      title={label}
      className={cn(
        "relative inline-flex size-11 shrink-0 items-center justify-center rounded-full transition-colors",
        tone === "onPrimary"
          ? "text-primary-foreground hover:bg-primary-foreground/15"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Bell aria-hidden className="size-5" />
      {unread ? (
        <span
          aria-hidden
          className="bg-destructive text-destructive-foreground absolute top-1 right-0.5 min-w-5 rounded-full px-1 text-center text-[11px] leading-5 font-semibold tabular-nums"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </Link>
  );
}
