import { StyleSheet, View, type ViewProps } from "react-native";

import { space, useTheme } from "@/lib/theme/theme";

export function Card({ style, ...props }: ViewProps) {
  const { colors, radius } = useTheme();
  return (
    <View
      {...props}
      style={[
        styles.card,
        { backgroundColor: colors.card, borderColor: colors.border, borderRadius: radius },
        style,
      ]}
    />
  );
}

const styles = StyleSheet.create({ card: { borderWidth: 1, padding: space[4], gap: space[2] } });
