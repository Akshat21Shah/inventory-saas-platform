"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

export type StatusTone = "info" | "warning" | "danger" | "success" | "progress" | "neutral";

// One mapping for the whole product so status colours are consistent everywhere (spec §8).
const TONES: Record<string, StatusTone> = {
  PLACED: "info",
  ON_HOLD: "warning",
  ACCEPTED: "progress",
  PACKED: "progress",
  DISPATCHED: "progress",
  DELIVERED: "success",
  COMPLETED: "success",
  REJECTED: "danger",
  CANCELLED: "neutral",
  IN_STOCK: "success",
  LOW_STOCK: "warning",
  BACKORDER: "info",
  UNAVAILABLE: "neutral",
  UNPAID: "warning",
  PARTIAL: "info",
  PAID: "success",
  ACTIVE: "success",
  SUSPENDED: "danger",
  BLOCKED: "warning",
};

const TONE_CLASSES: Record<StatusTone, string> = {
  info: "bg-info/12 text-info-strong ring-info/30",
  warning: "bg-warning/15 text-warning-strong ring-warning/35",
  danger: "bg-destructive/10 text-destructive ring-destructive/30",
  success: "bg-success/12 text-success-strong ring-success/30",
  progress: "bg-brand-100 text-brand-800 ring-brand-300",
  neutral: "bg-muted text-muted-foreground ring-border",
};

export function statusTone(status: string): StatusTone {
  return TONES[status] ?? "neutral";
}

/** Colour is always paired with a text label (never colour alone). */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const t = useTranslations("status");
  const tone = statusTone(status);
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {t.has(status) ? t(status) : status}
    </span>
  );
}
