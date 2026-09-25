import { formatDate, formatDateTime, formatMoney, formatQty } from "@/lib/format";
import { cn } from "@/lib/utils";

/** INR amount from a decimal string. Right-align in tables via `className="text-right"`. */
export function MoneyText({ value, className }: { value: string; className?: string }) {
  return <span className={cn("tabular-nums", className)}>{formatMoney(value)}</span>;
}

export function QtyText({
  value,
  unit,
  className,
}: {
  value: string;
  unit?: string;
  className?: string;
}) {
  return (
    <span className={cn("tabular-nums", className)}>
      {formatQty(value)}
      {unit ? ` ${unit}` : null}
    </span>
  );
}

/** Date (DD-MM-YYYY) or date-time in Asia/Kolkata, with a machine-readable `dateTime`. */
export function DateText({ value, withTime = false }: { value: string; withTime?: boolean }) {
  return <time dateTime={value}>{withTime ? formatDateTime(value) : formatDate(value)}</time>;
}
