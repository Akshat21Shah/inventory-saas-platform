/**
 * Money, quantities and dates as the web shows them, through the shared formatter (Indian
 * grouping, digits 0–9 in every language, IST dates). Values come from the server as decimal
 * strings and are never used for arithmetic here (thin client).
 */
import { Text } from "@/components/ui/text";
import { formatDate, formatDateTime, formatMoney, formatQty } from "@/lib/shared/format";

type TextProps = React.ComponentProps<typeof Text>;

export function MoneyText({ value, ...props }: TextProps & { value: string }) {
  return <Text {...props}>{formatMoney(value)}</Text>;
}

export function QtyText({ value, ...props }: TextProps & { value: string }) {
  return <Text {...props}>{formatQty(value)}</Text>;
}

export function DateText({
  value,
  withTime = false,
  ...props
}: TextProps & { value: string; withTime?: boolean }) {
  return <Text {...props}>{withTime ? formatDateTime(value) : formatDate(value)}</Text>;
}
