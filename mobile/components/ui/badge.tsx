import { StyleSheet, View } from "react-native";

import { useTheme } from "@/lib/theme/theme";

import { Text } from "./text";

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";

/** A status label: always words, never colour alone (spec §8). The web's StatusBadge: a dot, a
 * thin ring and a tinted fill in the tone's colour. */
export function Badge({ label, tone = "neutral" }: { label: string; tone?: BadgeTone }) {
  const { colors } = useTheme();
  // [fill, text, ring], the web's TONE_CLASSES (bg-x/12, text-x-strong, ring-x/30).
  const [background, foreground, ring] = {
    neutral: [colors.muted, colors.mutedForeground, colors.border],
    success: [colors.success + "1f", colors.successStrong, colors.success + "4d"],
    warning: [colors.warning + "26", colors.warningStrong, colors.warning + "59"],
    danger: [colors.destructive + "1a", colors.destructive, colors.destructive + "4d"],
    info: [colors.info + "1f", colors.infoStrong, colors.info + "4d"],
    brand: [colors.brand100, colors.brand800, colors.brand300],
  }[tone];
  return (
    <View style={[styles.badge, { backgroundColor: background, borderColor: ring }]}>
      <View style={[styles.dot, { backgroundColor: foreground }]} />
      <Text size="xs" weight="medium" style={{ color: foreground }}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: 999,
    borderWidth: 1,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
});
