import { Redirect, Slot } from "expo-router";

import { useAuth } from "@/lib/auth/auth-provider";
import { CartProvider } from "@/lib/cart/cart-state";

/** Every shop screen needs a session, and shares one cart. */
export default function ShopLayout() {
  const { status } = useAuth();
  if (status === "loading") return null;
  if (status !== "signedIn") return <Redirect href="/sign-in" />;
  return (
    <CartProvider>
      <Slot />
    </CartProvider>
  );
}
