import { Platform, Text as NativeText, type TextProps } from "react-native";

import { text, useTheme } from "@/lib/theme/theme";

type Tone = "default" | "muted" | "primary" | "danger" | "success" | "warning" | "onPrimary";
type Size = keyof typeof text;

const WEIGHTS = { normal: "400", medium: "500", semibold: "600", bold: "700" } as const;

/**
 * On Android, medium and semibold are the system's medium family rather than a numeric weight:
 * React Native measures Devanagari at a numeric 500/600 narrower than Android draws it, so the
 * last words of a line were cut off ("सब कार्ट में जोड़ें"). The family is measured as drawn.
 */
function fontFor(weight: keyof typeof WEIGHTS) {
  if (Platform.OS === "android" && (weight === "medium" || weight === "semibold")) {
    return { fontFamily: "sans-serif-medium", fontWeight: "400" as const };
  }
  return { fontWeight: WEIGHTS[weight] };
}

/** Every text on screen. The phone's system font (Devanagari included, no bundled fonts). */
export function Text({
  tone = "default",
  size = "base",
  weight = "normal",
  style,
  ...props
}: TextProps & { tone?: Tone; size?: Size; weight?: keyof typeof WEIGHTS }) {
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
  return (
    <NativeText
      {...props}
      style={[
        {
          color,
          fontSize: text[size],
          lineHeight: Math.round(text[size] * 1.45),
          ...fontFor(weight),
        },
        style,
      ]}
    />
  );
}
