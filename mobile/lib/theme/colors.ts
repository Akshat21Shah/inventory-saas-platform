/**
 * The app's colours: the web's tokens (`lib/shared/tokens.ts`) with the distributor's brand
 * applied at runtime, made by the web's own palette function (`brandCssVariables`) and converted
 * from OKLCH to hex for React Native (ADR-061 item 5).
 */
import { brandCssVariables, DEFAULT_BRAND_COLOR, isHexColor } from "@/lib/shared/palette";
import { colors as tokens } from "@/lib/shared/tokens";

const OKLCH = /^oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)$/;

/** OKLCH (as the web writes it) → sRGB hex. */
export function oklchToHex(css: string): string {
  const match = OKLCH.exec(css);
  if (!match) throw new Error(`Not an OKLCH colour: ${css}`);
  const [l, c, h] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const rad = (h * Math.PI) / 180;
  const a = c * Math.cos(rad);
  const b = c * Math.sin(rad);
  const L = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const M = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const S = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const linear = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
  const gamma = (x: number) => (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055);
  return (
    "#" +
    linear
      .map((x) =>
        Math.round(Math.min(1, Math.max(0, gamma(x))) * 255)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("")
  );
}

export type Colors = { -readonly [K in keyof typeof tokens]: string };

/** The full colour set for a distributor's brand colour (the platform's when none). */
export function colorsFor(brandHex?: string | null): Colors {
  const hex = brandHex && isHexColor(brandHex) ? brandHex : DEFAULT_BRAND_COLOR;
  const out: Colors = { ...tokens };
  for (const [name, value] of Object.entries(brandCssVariables(hex))) {
    const key = name
      .replace(/^--/, "")
      .replace(/-([a-z0-9])/g, (_, ch: string) => ch.toUpperCase());
    if (key in out) out[key as keyof Colors] = oklchToHex(value);
  }
  return out;
}
