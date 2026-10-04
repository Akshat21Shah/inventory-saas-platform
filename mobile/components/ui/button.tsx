import { ActivityIndicator, Pressable, StyleSheet, View, type PressableProps } from "react-native";

import { NeedsInternet } from "@/components/app/offline";
import { useOnline } from "@/lib/offline/online";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

import { Text } from "./text";

type Variant = "primary" | "outline" | "ghost" | "danger";

/** A button at least 48 × 48 (CLAUDE.md §6a); `busy` shows a spinner and blocks double taps.
 * `needsInternet`: off while the phone is offline, saying so underneath (ADR-061 item 10). */
export function Button({
  label,
  variant = "primary",
  busy = false,
  disabled,
  icon,
  style,
  needsInternet = false,
  ...props
}: Omit<PressableProps, "children"> & {
  label: string;
  variant?: Variant;
  busy?: boolean;
  icon?: React.ReactNode;
  needsInternet?: boolean;
}) {
  const { colors, radius } = useTheme();
  const online = useOnline();
  const waiting = needsInternet && !online;
  const off = Boolean(disabled) || busy || waiting;
  const background = {
    primary: colors.primary,
    outline: colors.background,
    ghost: "transparent",
    danger: colors.destructive,
  }[variant];
  const tone = variant === "primary" || variant === "danger" ? "onPrimary" : "default";
  const button = (
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
  if (!waiting) return button;
  return (
    <View style={styles.waiting}>
      {button}
      <NeedsInternet />
    </View>
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
  waiting: { gap: space[1] },
});
