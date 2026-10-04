// Synced from web/app/globals.css by scripts/sync-from-web.mjs (npm run sync). Do not edit.
/** The web's light theme, as hex. The brand colours are replaced at runtime by the distributor's. */
export const colors = {
  background: "#ffffff",
  foreground: "#0a0a0a",
  card: "#ffffff",
  cardForeground: "#0a0a0a",
  popover: "#ffffff",
  popoverForeground: "#0a0a0a",
  primary: "#171717",
  primaryForeground: "#fafafa",
  secondary: "#f5f5f5",
  secondaryForeground: "#171717",
  muted: "#f5f5f5",
  mutedForeground: "#737373",
  accent: "#f5f5f5",
  accentForeground: "#171717",
  destructive: "#e7000b",
  border: "#e5e5e5",
  input: "#e5e5e5",
  ring: "#a1a1a1",
  brand50: "#eef5ff",
  brand100: "#ddebff",
  brand200: "#bed7ff",
  brand300: "#97bbff",
  brand400: "#719bff",
  brand500: "#517df4",
  brand600: "#3c63d8",
  brand700: "#2c4eb3",
  brand800: "#1f3a8b",
  brand900: "#162a67",
  brand950: "#0a1843",
  success: "#32a155",
  successStrong: "#0b5d2a",
  warning: "#efa30f",
  warningStrong: "#864900",
  info: "#0089d0",
  infoStrong: "#005189",
} as const;

export type ColorToken = keyof typeof colors;

/** The web's --radius in density-independent pixels (rem × 16). */
export const radius = 10;
