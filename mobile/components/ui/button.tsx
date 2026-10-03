import { ActivityIndicator, Pressable, StyleSheet, View, type PressableProps } from "react-native";

import { space, TOUCH, useTheme } from "@/lib/theme/theme";

import { Text } from "./text";

type Variant = "primary" | "outline" | "ghost" | "danger";

/** A button at least 48 × 48 (CLAUDE.md §6a); `busy` shows a spinner and blocks double taps. */
export function Button({
  label,
  variant = "primary",
  busy = false,
  disabled,
  icon,
  style,
  ...props
}: Omit<PressableProps, "children"> & {
  label: string;
  variant?: Variant;
  busy?: boolean;
  icon?: React.ReactNode;
}) {
  const { colors, radius } = useTheme();
  const off = Boolean(disabled) || busy;
  const background = {
    primary: colors.primary,
    outline: colors.background,
    ghost: "transparent",
    danger: colors.destructive,
  }[variant];
  const tone = variant === "primary" || variant === "danger" ? "onPrimary" : "default";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: off, busy }}
      disabled={off}
      {...props}
      style={(state) => [
        styles.base,
        {
          backgroundColor: background,
          borderRadius: radius,
          borderColor: variant === "outline" ? colors.border : "transparent",
          opacity: off ? 0.55 : state.pressed ? 0.85 : 1,
        },
        typeof style === "function" ? style(state) : style,
      ]}
    >
      {busy ? (
        <ActivityIndicator
          color={tone === "onPrimary" ? colors.primaryForeground : colors.primary}
        />
      ) : (
        <View style={styles.row}>
          {icon}
          <Text tone={tone} weight="semibold" style={styles.label}>
            {label}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: TOUCH,
    minWidth: TOUCH,
    paddingHorizontal: space[4],
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 1,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: space[2],
    maxWidth: "100%",
  },
  label: { textAlign: "center", flexShrink: 1 },
});
