import { forwardRef } from "react";
import { StyleSheet, TextInput, View, type TextInputProps } from "react-native";

import { space, text, TOUCH, useTheme } from "@/lib/theme/theme";

import { Text } from "./text";

/** A labelled input, 48 tall; the error is read out with the field (accessibility). */
export const Input = forwardRef<
  TextInput,
  TextInputProps & { label: string; error?: string | null; hint?: string }
>(function Input({ label, error, hint, style, ...props }, ref) {
  const { colors, radius } = useTheme();
  return (
    <View style={styles.field}>
      <Text weight="medium" size="sm">
        {label}
      </Text>
      <TextInput
        ref={ref}
        accessibilityLabel={label}
        accessibilityHint={error ?? hint}
        placeholderTextColor={colors.mutedForeground}
        {...props}
        style={[
          styles.input,
          {
            borderColor: error ? colors.destructive : colors.input,
            borderRadius: radius,
            color: colors.foreground,
          },
          style,
        ]}
      />
      {error ? (
        <Text tone="danger" size="sm" accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : hint ? (
        <Text tone="muted" size="sm">
          {hint}
        </Text>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  field: { gap: space[1] },
  input: { minHeight: TOUCH, borderWidth: 1, paddingHorizontal: space[3], fontSize: text.lg },
});
