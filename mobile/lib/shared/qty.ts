// Synced from web/lib/qty.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
/**
 * Quantity steps for the order stepper: the product's minimum, then its order multiple. Only to
 * help the shop tap to a quantity the server will accept; the server still checks every quantity
 * (CLAUDE.md §4, thin client). Quantities arrive as decimal strings with up to 3 decimals and are
 * handled as whole thousandths, never as floating point numbers.
 */

const QTY_RE = /^\d+(\.\d{1,3})?$/;

/** "12.5" → 12500 thousandths; null when it isn't a plain quantity. */
export function toMilli(value: string): number | null {
  const text = value.trim();
  if (!QTY_RE.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  return Number(whole) * 1000 + Number(fraction.padEnd(3, "0"));
}

/** 12500 → "12.5" (no trailing zeros). */
export function fromMilli(milli: number): string {
  const whole = Math.floor(milli / 1000);
  const fraction = String(milli % 1000)
    .padStart(3, "0")
    .replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : String(whole);
}

function step(multiple: string): number {
  const m = toMilli(multiple);
  return m && m > 0 ? m : 1000;
}

/** The smallest quantity that can be ordered: the minimum, rounded up to the multiple. */
export function firstQty(min: string, multiple: string): string {
  const s = step(multiple);
  const lowest = Math.max(toMilli(min) ?? 0, s);
  return fromMilli(Math.ceil(lowest / s) * s);
}

export function nextQty(current: string, min: string, multiple: string): string {
  const now = toMilli(current) ?? 0;
  if (now <= 0) return firstQty(min, multiple);
  const s = step(multiple);
  return fromMilli((Math.floor(now / s) + 1) * s);
}

/** One step down; below the minimum means "remove" ("0"). */
export function previousQty(current: string, min: string, multiple: string): string {
  const now = toMilli(current) ?? 0;
  const s = step(multiple);
  const down = (Math.ceil(now / s) - 1) * s;
  const lowest = toMilli(firstQty(min, multiple)) ?? s;
  return down < lowest ? "0" : fromMilli(down);
}

export function isZero(value: string): boolean {
  return (toMilli(value) ?? 0) === 0;
}
