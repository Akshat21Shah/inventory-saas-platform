// Synced from web/lib/theme/palette.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
/**
 * Tenant brand palette: one primary colour (hex) → a full 50–950 scale in OKLCH, exposed as CSS
 * variables so every component follows the tenant's branding (CLAUDE.md §6).
 */

export const DEFAULT_BRAND_COLOR = "#2f5bea";
const HEX_RE = /^#([0-9a-f]{6})$/i;

export interface Oklch {
  l: number;
  c: number;
  h: number;
}

const toLinear = (channel: number) =>
  channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;

export function isHexColor(value: string): boolean {
  return HEX_RE.test(value);
}

export function hexToOklch(hex: string): Oklch {
  const match = HEX_RE.exec(hex);
  if (!match?.[1]) throw new Error(`Invalid hex colour: ${hex}`);
  const n = parseInt(match[1], 16);
  const r = toLinear(((n >> 16) & 255) / 255);
  const g = toLinear(((n >> 8) & 255) / 255);
  const b = toLinear((n & 255) / 255);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const c = Math.sqrt(A * A + B * B);
  const h = ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360;
  return { l: L, c, h };
}

const round = (value: number, digits: number) => Number(value.toFixed(digits));
export const oklchCss = ({ l, c, h }: Oklch) =>
  `oklch(${round(l, 3)} ${round(c, 3)} ${round(h, 1)})`;

// Lightness targets and chroma factors per shade (tuned for readable UI tints and text).
const SCALE: ReadonlyArray<readonly [number, number, number]> = [
  [50, 0.97, 0.12],
  [100, 0.94, 0.25],
  [200, 0.88, 0.45],
  [300, 0.8, 0.7],
  [400, 0.71, 0.9],
  [500, 0.62, 1],
  [600, 0.54, 1],
  [700, 0.46, 0.9],
  [800, 0.38, 0.75],
  [900, 0.31, 0.6],
  [950, 0.23, 0.45],
];

/** Readable text colour on top of the brand colour. */
export function foregroundFor(color: Oklch): string {
  return color.l > 0.68 ? "oklch(0.18 0 0)" : "oklch(0.985 0 0)";
}

export function brandCssVariables(hex: string): Record<string, string> {
  const base = hexToOklch(isHexColor(hex) ? hex : DEFAULT_BRAND_COLOR);
  const vars: Record<string, string> = {};
  for (const [step, lightness, chromaFactor] of SCALE) {
    vars[`--brand-${step}`] = oklchCss({ l: lightness, c: base.c * chromaFactor, h: base.h });
  }
  vars["--primary"] = oklchCss(base);
  vars["--primary-foreground"] = foregroundFor(base);
  vars["--ring"] = vars["--brand-400"] ?? oklchCss(base);
  vars["--sidebar-primary"] = vars["--primary"];
  vars["--sidebar-primary-foreground"] = vars["--primary-foreground"];
  return vars;
}

export function brandStyleSheet(hex: string): string {
  const body = Object.entries(brandCssVariables(hex))
    .map(([name, value]) => `${name}:${value}`)
    .join(";");
  // Doubled selector wins over the static defaults in globals.css regardless of stylesheet order.
  return `:root:root{${body}}`;
}
