/** The search a list opens with: `?q=` when global search's "See all" led here (client only). */
export function initialQuery(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("q") ?? "";
}
