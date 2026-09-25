/**
 * Display formatting only (INR, quantities, IST dates). Values arrive from the API as decimal
 * strings and are never converted to floating point numbers or used for arithmetic here
 * (thin client, CLAUDE.md §4).
 */

const DECIMAL_RE = /^-?\d+(\.\d+)?$/;
const TIME_ZONE = "Asia/Kolkata";

const inrFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function assertDecimal(value: string): Intl.StringNumericLiteral {
  if (!DECIMAL_RE.test(value)) throw new Error(`Not a decimal string: ${value}`);
  return value as Intl.StringNumericLiteral;
}

/** "123456.5" → "₹1,23,456.50" */
export function formatMoney(value: string): string {
  return inrFormatter.format(assertDecimal(value));
}

/** "1234.500" → "1,234.5" (up to 3 decimals, Indian grouping) */
export function formatQty(value: string, maximumFractionDigits = 3): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits }).format(assertDecimal(value));
}

function parts(value: Date | string, options: Intl.DateTimeFormatOptions) {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) throw new Error(`Invalid date: ${String(value)}`);
  const map: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat("en-GB", {
    timeZone: TIME_ZONE,
    ...options,
  }).formatToParts(date)) {
    map[part.type] = part.value;
  }
  return map;
}

/** ISO timestamp or date → "DD-MM-YYYY" in Asia/Kolkata */
export function formatDate(value: Date | string): string {
  const p = parts(value, { day: "2-digit", month: "2-digit", year: "numeric" });
  return `${p.day}-${p.month}-${p.year}`;
}

/** ISO timestamp → "DD-MM-YYYY, HH:mm" in Asia/Kolkata (24h) */
export function formatDateTime(value: Date | string): string {
  const p = parts(value, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return `${p.day}-${p.month}-${p.year}, ${p.hour}:${p.minute}`;
}
