/**
 * One stack per tab (owner, checkpoint review: the bottom bar stays on every shopping screen, as
 * on the web). A category, a search, a product or an order opens inside the tab the shop is in,
 * so the cart is one tap away from anywhere.
 */
import { Stack } from "expo-router";

import { useAuth } from "@/lib/auth/auth-provider";
import { useTheme } from "@/lib/theme/theme";

export const unstable_settings = {
  home: { initialRouteName: "index" },
  catalog: { initialRouteName: "catalog/index" },
  cart: { initialRouteName: "cart" },
  orders: { initialRouteName: "orders/index" },
  account: { initialRouteName: "account/index" },
};

export default function TabStack() {
  const { colors } = useTheme();
  const { branding } = useAuth();
  return (
    <Stack
      screenOptions={{
        // The distributor's name, as the web shop's header; pages set their own titles.
        title: branding?.display_name ?? "",
        headerStyle: { backgroundColor: colors.primary },
        headerTintColor: colors.primaryForeground,
        headerTitleStyle: { fontWeight: "600" },
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
