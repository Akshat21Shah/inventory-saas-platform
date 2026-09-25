"use client";

import { useState } from "react";

interface CursorPage {
  next?: string | null;
  previous?: string | null;
}

function cursorOf(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return new URL(url, "http://localhost").searchParams.get("cursor") ?? undefined;
}

/** Cursor pagination state for a DataTable: the server decides the pages (thin client). */
export function useCursor() {
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  return {
    cursor,
    reset: () => setCursor(undefined),
    pagination: (page: CursorPage | undefined) =>
      page && (page.next || page.previous)
        ? {
            hasNext: Boolean(page.next),
            hasPrevious: Boolean(page.previous),
            onNext: () => setCursor(cursorOf(page.next)),
            onPrevious: () => setCursor(cursorOf(page.previous)),
          }
        : undefined,
  };
}
