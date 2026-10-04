import { createContext, useContext, useMemo, type ReactNode } from "react";

import { radius } from "@/lib/shared/tokens";

import { colorsFor, type Colors } from "./colors";

/** Spacing in density-independent pixels (a 4-point scale, like the web's Tailwind spacing). */
export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40 } as const;
/** Text sizes: the web's text-xs … text-2xl. */
export const text = { xs: 12, sm: 14, base: 16, lg: 18, xl: 20, "2xl": 24 } as const;
/** The smallest touch target on a phone (CLAUDE.md §6a). */
export const TOUCH = 48;

export interface Theme {
  colors: Colors;
  radius: number;
}

const ThemeContext = createContext<Theme>({ colors: colorsFor(null), radius });

/** The distributor's colours for every screen below (the platform's before sign-in). */
export function ThemeProvider({ brand, children }: { brand: string | null; children: ReactNode }) {
  const value = useMemo(() => ({ colors: colorsFor(brand), radius }), [brand]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}
