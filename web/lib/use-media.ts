"use client";

import { useSyncExternalStore } from "react";

/** Tailwind's breakpoints (px), the single source for layout switches done in code. */
export const BREAKPOINTS = { md: 768, lg: 1024 } as const;

function subscribe(query: string) {
  return (onChange: () => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
    const media = window.matchMedia(query);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  };
}

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    subscribe(query),
    () =>
      typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false,
    () => false, // server render: the wide layout, corrected on the client
  );
}

/** Below 768 px: phones (filter sheet, sticky form actions). */
export function useIsPhone(): boolean {
  return useMedia(`(max-width: ${BREAKPOINTS.md - 0.02}px)`);
}

/** Below 1024 px: phones and tablets (lists as cards instead of tables). */
export function useIsCompact(): boolean {
  return useMedia(`(max-width: ${BREAKPOINTS.lg - 0.02}px)`);
}
