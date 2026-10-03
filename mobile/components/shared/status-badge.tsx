import { Badge, type BadgeTone } from "@/components/ui/badge";
import { useTranslations } from "@/lib/i18n/translations";

// The web's mapping (components/shared/status-badge.tsx) for what a shop sees: the same colour
// for the same status everywhere, always with its words.
const TONES: Record<string, BadgeTone> = {
  PLACED: "info",
  ON_HOLD: "warning",
  ACCEPTED: "brand",
  PACKED: "brand",
  DISPATCHED: "brand",
  DELIVERED: "success",
  PARTLY_DELIVERED: "info",
  COMPLETED: "success",
  REJECTED: "danger",
  CANCELLED: "neutral",
  IN_STOCK: "success",
  LOW_STOCK: "warning",
  BACKORDER: "info",
  OUT_OF_STOCK: "danger",
  UNPAID: "warning",
  PARTIAL: "info",
  PAID: "success",
  ISSUED: "success",
  RECEIVED: "success",
  PENDING_CLEARANCE: "warning",
  CLEARED: "success",
  BOUNCED: "danger",
  REVERSED: "neutral",
  REQUESTED: "warning",
  APPROVED: "success",
  CREATED: "info",
  ATTEMPTED: "warning",
  EXPIRED: "neutral",
  PENDING: "warning",
  FAILED: "danger",
};

type Labels =
  | "status"
  | "orderStatus"
  | "shipmentStatus"
  | "paymentStatus"
  | "refundStatus"
  | "deliveryStatus"
  | "checkoutStatus"
  | "returnRequestStatus"
  | "shopReturnStatus";

export function StatusBadge({ status, labels = "status" }: { status: string; labels?: Labels }) {
  const t = useTranslations(labels);
  return <Badge tone={TONES[status] ?? "neutral"} label={t.has(status) ? t(status) : status} />;
}
