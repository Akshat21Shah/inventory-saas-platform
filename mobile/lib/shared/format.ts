// Synced from web/lib/format.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
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

const numberFormatter = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
const compactFormatter = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/**
 * The one formatter for a number inside a message (ADR-060 item 4): Indian grouping and the
 * digits 0–9 in every language, 6029 → "6,029", 123456 → "1,23,456". Translations apply it to
 * every number they are given (`lib/i18n/translations.ts`); the backend has the same rule.
 */
export function formatNumber(value: number | bigint): string {
  return numberFormatter.format(value);
}

/** Chart axes: 12000 → "12K", 250000 → "2.5L", the same in every language. */
export function formatCompact(value: number): string {
  return compactFormatter.format(value);
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

/** Chart ticks: "28 Sept" in the screen's language (its locale keeps the digits 0–9). */
export function formatDayMonth(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    timeZone: TIME_ZONE,
  }).format(new Date(`${value}T00:00:00+05:30`));
}

/** "+919876543210" → "+91 98765 43210" for display; anything else is returned unchanged. */
export function formatIndianMobile(phone: string): string {
  const match = /^\+91(\d{5})(\d{5})$/.exec(phone);
  return match ? `+91 ${match[1]} ${match[2]}` : phone;
}
