import type { ReactNode } from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";

import { space, useTheme } from "@/lib/theme/theme";

/**
 * A screen's body: a centred column (up to 640 on large phones and tablets, like the web shop's
 * column), scrolling, with pull-to-refresh when given. Lists use their own virtualised list.
 */
export function Screen({
  children,
  scroll = true,
  refreshing,
  onRefresh,
  // Inside the tabs the tab bar keeps clear of the phone's bottom edge; pages above the tabs
  // (a product, an order) pass ["bottom"], full-screen pages ["top", "bottom"].
  edges = [],
  footer,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  edges?: Edge[];
  footer?: ReactNode;
}) {
  const { colors } = useTheme();
  const body = <View style={styles.column}>{children}</View>;
  return (
    <SafeAreaView edges={edges} style={[styles.root, { backgroundColor: colors.background }]}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            onRefresh ? (
              <RefreshControl
                refreshing={Boolean(refreshing)}
                onRefresh={onRefresh}
                colors={[colors.primary]}
              />
            ) : undefined
          }
        >
          {body}
        </ScrollView>
      ) : (
        <View style={[styles.content, styles.fill]}>{body}</View>
      )}
      {footer ? (
        <View
          style={[
            styles.footer,
            { borderTopColor: colors.border, backgroundColor: colors.background },
          ]}
        >
          <View style={styles.column}>{footer}</View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  fill: { flex: 1 },
  content: { padding: space[4], paddingBottom: space[8] },
  column: { width: "100%", maxWidth: 640, alignSelf: "center", gap: space[4] },
  footer: { padding: space[3], borderTopWidth: 1 },
});
