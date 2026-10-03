import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/lib/auth/auth-provider";
import { CartProvider } from "@/lib/cart/cart-state";
import { useTheme } from "@/lib/theme/theme";

/** Every shop screen needs a session; screens above the tabs get a header in the brand colour. */
export default function ShopLayout() {
  const { status } = useAuth();
  const { colors } = useTheme();
  if (status === "loading") return null;
  if (status !== "signedIn") return <Redirect href="/sign-in" />;
  return (
    <CartProvider>
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.primary },
          headerTintColor: colors.primaryForeground,
          headerTitleStyle: { fontWeight: "600" },
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      </Stack>
    </CartProvider>
  );
}
