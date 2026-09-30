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
  PARTLY_DELIVERED: "info",
  COMPLETED: "success",
  ALLOCATED: "progress",
  PROPOSED: "info",
  CONFIRMED: "success",
  SKIPPED_CREDIT: "warning",
  SKIPPED_BLOCKED: "warning",
  REJECTED: "danger",
  CANCELLED: "neutral",
  IN_STOCK: "success",
  LOW_STOCK: "warning",
  BACKORDER: "info",
  UNAVAILABLE: "neutral",
  LOW: "warning",
  OUT: "danger",
  OUT_OF_STOCK: "danger",
  DRAFT: "neutral",
  POSTED: "success",
  UNPAID: "warning",
  PARTIAL: "info",
  PAID: "success",
  ACTIVE: "success",
  SUSPENDED: "danger",
  BLOCKED: "warning",
  RECEIVED: "success",
  PENDING_CLEARANCE: "warning",
  CLEARED: "success",
  BOUNCED: "danger",
  REVERSED: "neutral",
  WITH_SALESMAN: "warning",
  HANDED_OVER: "success",
  NOT_NEEDED: "neutral",
  ISSUED: "success",
  PENDING: "warning",
  SENDING: "progress",
  SENT: "success",
  FAILED: "danger",
  SKIPPED: "neutral",
  UNVERIFIED: "neutral",
  CHECKING: "progress",
  VERIFIED: "success",
  GENERATED: "success",
  SUBMITTED: "progress",
  CANCELLING: "progress",
  CREATED: "info",
  ATTEMPTED: "warning",
  EXPIRED: "neutral",
  NEEDS_REVIEW: "warning",
  NOT_SUBMITTED: "neutral",
  APPROVED: "success",
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

/** Colour is always paired with a text label (never colour alone). `labels` picks the wording
 * where one code means different things (an order's ACCEPTED vs an invitation's). */
export function StatusBadge({
  status,
  className,
  labels = "status",
}: {
  status: string;
  className?: string;
  labels?:
    | "status"
    | "orderStatus"
    | "shipmentStatus"
    | "allocationStatus"
    | "paymentStatus"
    | "handoverStatus"
    | "refundStatus"
    | "deliveryStatus"
    | "connectionStatus"
    | "einvoiceStatus"
    | "ewaybillStatus"
    | "checkoutStatus"
    | "approvalStatus";
}) {
  const t = useTranslations(labels);
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
