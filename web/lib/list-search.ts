"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

/**
 * A list's search box: it opens with `?q=` when global search's "See all" led here, and follows a
 * later "See all" while the list is open. Read from the router, not `window.location`, which
 * changes only after the new page's first render on an in-app navigation. Pages using it wrap the
 * list in <Suspense> (useSearchParams).
 */
export function useListSearch(): [string, (value: string) => void] {
  const q = useSearchParams().get("q") ?? "";
  const [search, setSearch] = useState(q);
  const [from, setFrom] = useState(q);
  if (q !== from) {
    setFrom(q);
    setSearch(q);
  }
  return [search, setSearch];
}
