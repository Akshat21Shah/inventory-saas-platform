import Feather from "@expo/vector-icons/Feather";
import { Tabs } from "expo-router";
import type { ColorValue } from "react-native";

import { useAuth } from "@/lib/auth/auth-provider";
import { useCart } from "@/lib/cart/cart-state";
import { useTranslations } from "@/lib/i18n/translations";
import { useTheme } from "@/lib/theme/theme";

type Icon = keyof typeof Feather.glyphMap;

/** The shop's bottom navigation, as on the web: Home, Catalog, Cart, Orders, Account. */
export default function ShopTabs() {
  const t = useTranslations("nav");
  const { colors } = useTheme();
  const { branding } = useAuth();
  // Products in the cart, as the web's bottom bar shows; it follows each tap at once (the cart
  // state counts taps the server hasn't confirmed yet).
  const { count } = useCart();
  const icon = (name: Icon) => {
    const TabIcon = ({ color, size }: { color: ColorValue; size: number }) => (
      <Feather name={name} color={color} size={size} />
    );
    return TabIcon;
  };
  return (
    <Tabs
      screenOptions={{
        // The distributor's name on every tab, as the web shop's header; pages carry their own title.
        headerTitle: branding?.display_name ?? "",
        headerStyle: { backgroundColor: colors.primary },
        headerTintColor: colors.primaryForeground,
        headerTitleStyle: { fontWeight: "600" },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.mutedForeground,
        tabBarLabelStyle: { fontSize: 12 },
        tabBarStyle: { minHeight: 60 },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      <Tabs.Screen name="index" options={{ title: t("home"), tabBarIcon: icon("home") }} />
      <Tabs.Screen name="catalog" options={{ title: t("catalog"), tabBarIcon: icon("search") }} />
      <Tabs.Screen
        name="cart"
        options={{
          title: t("cart"),
          tabBarIcon: icon("shopping-cart"),
          tabBarBadge: count > 0 ? (count > 99 ? "99+" : count) : undefined,
          tabBarBadgeStyle: {
            backgroundColor: colors.destructive,
            color: colors.primaryForeground,
          },
        }}
      />
      <Tabs.Screen name="orders" options={{ title: t("orders"), tabBarIcon: icon("clipboard") }} />
      <Tabs.Screen name="account" options={{ title: t("account"), tabBarIcon: icon("user") }} />
    </Tabs>
  );
}
