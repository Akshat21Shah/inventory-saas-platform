import { Platform, Text as NativeText, type TextProps } from "react-native";

import { text, useTheme } from "@/lib/theme/theme";

type Tone = "default" | "muted" | "primary" | "danger" | "success" | "warning" | "onPrimary";
type Size = keyof typeof text;

const WEIGHTS = { normal: "400", medium: "500", semibold: "600", bold: "700" } as const;
type Weight = keyof typeof WEIGHTS;

const DEVANAGARI = /[\u0900-\u097F]/;

/** The words of a text whose children are plain strings (most of them). */
function wordsOf(children: TextProps["children"]): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map((child) => wordsOf(child)).join("");
  return "";
}

/**
 * On Android, medium and semibold are a medium font rather than a numeric weight, which React
 * Native measures narrower than Android draws it for Devanagari. Devanagari at those weights is
 * the bundled Noto Sans Devanagari Medium (the web's font): many phones' own Devanagari fonts have
 * no medium, so Hindi and Marathi headings came out regular (owner, checkpoint review item 6).
 */
function fontFor(weight: Weight, devanagari: boolean) {
  if (Platform.OS === "android" && (weight === "medium" || weight === "semibold")) {
    return { fontFamily: devanagari ? "NotoSansDevanagari-Medium" : "sans-serif-medium" };
  }
  return weight === "normal" ? {} : { fontWeight: WEIGHTS[weight] };
}

/** Every text on screen: the phone's system font, plus one bundled Devanagari medium. */
export function Text({
  tone = "default",
  size = "base",
  weight = "normal",
  style,
  ...props
}: TextProps & { tone?: Tone; size?: Size; weight?: Weight }) {
  const { colors } = useTheme();
  const color = {
    default: colors.foreground,
    muted: colors.mutedForeground,
    primary: colors.primary,
    danger: colors.destructive,
    success: colors.successStrong,
    warning: colors.warningStrong,
    onPrimary: colors.primaryForeground,
  }[tone];
  // Devanagari keeps its font's own line spacing on Android. With a set line height, React
  // Native sizes a short label to its measured width and Android's line breaker can find the
  // words a fraction wider, moving the last word to a hidden second line ("ऑर्डर हुआ" showed as
  // "ऑर्डर"). Without one, a label that fits stays on one line.
  const devanagari = Platform.OS === "android" && DEVANAGARI.test(wordsOf(props.children));
  const lineHeight = devanagari ? undefined : Math.round(text[size] * 1.45);
  return (
    <NativeText
      {...props}
      style={[{ color, fontSize: text[size], lineHeight, ...fontFor(weight, devanagari) }, style]}
    />
  );
}
