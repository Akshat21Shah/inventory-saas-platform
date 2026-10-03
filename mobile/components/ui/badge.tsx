import { StyleSheet, View } from "react-native";

import { space, useTheme } from "@/lib/theme/theme";

import { Text } from "./text";

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";

/** A status label: always words, never colour alone (spec §8). */
export function Badge({ label, tone = "neutral" }: { label: string; tone?: BadgeTone }) {
  const { colors } = useTheme();
  const [background, foreground] = {
    neutral: [colors.muted, colors.foreground],
    success: [colors.success + "26", colors.successStrong],
    warning: [colors.warning + "33", colors.warningStrong],
    danger: [colors.destructive + "1f", colors.destructive],
    info: [colors.info + "26", colors.infoStrong],
    brand: [colors.brand100, colors.brand800],
  }[tone];
  return (
    <View style={[styles.badge, { backgroundColor: background }]}>
      <Text size="xs" weight="semibold" style={{ color: foreground }}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: space[2],
    paddingVertical: 2,
    borderRadius: 999,
  },
});
