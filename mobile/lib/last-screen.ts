import { usePathname } from "expo-router";
import { useEffect } from "react";

/** The last shopping screen the shop was on before Account, sent with "Suggest a better word" so
 * the people who look after the words know where it was (the web sends the page's address). */
let lastScreen = "/shop";

export function lastShoppingScreen(): string {
  return lastScreen;
}

export function useTrackScreen(): void {
  const pathname = usePathname();
  useEffect(() => {
    if (!pathname.startsWith("/shop/account")) lastScreen = pathname;
  }, [pathname]);
}
