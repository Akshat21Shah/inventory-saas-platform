import Feather from "@expo/vector-icons/Feather";
import { useEffect, useState } from "react";
import { Animated, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

/** Nothing here yet, in plain words, with what to do next. */
export function EmptyState({
  icon = "inbox",
  title,
  body,
  action,
}: {
  icon?: keyof typeof Feather.glyphMap;
  title: string;
  body?: string;
  action?: { label: string; onPress: () => void };
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.centre} accessibilityRole="summary">
      <Feather name={icon} size={36} color={colors.mutedForeground} />
      <Text weight="semibold" size="lg" style={styles.text}>
        {title}
      </Text>
      {body ? (
        <Text tone="muted" style={styles.text}>
          {body}
        </Text>
      ) : null}
      {action ? <Button label={action.label} onPress={action.onPress} variant="outline" /> : null}
    </View>
  );
}

/** A failed load: the server's or the app's words, never a raw error, and "Try again". */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useTranslations("common");
  const errors = useErrorText();
  const { colors } = useTheme();
  return (
    <View style={styles.centre} accessibilityRole="alert">
      <Feather name="alert-circle" size={36} color={colors.destructive} />
      <Text weight="semibold" size="lg" style={styles.text}>
        {errors.message(error)}
      </Text>
      {onRetry ? <Button label={t("retry")} onPress={onRetry} variant="outline" /> : null}
    </View>
  );
}

/** Grey blocks while a screen loads (the web's skeletons). */
export function Skeleton({
  height = 20,
  width = "100%",
}: {
  height?: number;
  width?: number | `${number}%`;
}) {
  const { colors, radius } = useTheme();
  const [pulse] = useState(() => new Animated.Value(0.5));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.5, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ height, width, borderRadius: radius, backgroundColor: colors.muted, opacity: pulse }}
    />
  );
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <View style={{ gap: space[3] }} accessibilityLabel="…">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={72} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  centre: {
    alignItems: "center",
    gap: space[3],
    paddingVertical: space[8],
    paddingHorizontal: space[4],
  },
  text: { textAlign: "center" },
});
