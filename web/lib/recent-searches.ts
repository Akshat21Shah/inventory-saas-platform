/** The person's recent global searches, kept in this browser only (per person; a convenience,
 * so storage that is unavailable or full is ignored). */
const LIMIT = 8;

function key(personId: string): string {
  return `search.recent.${personId}`;
}

export function recentSearches(personId: string | undefined): string[] {
  if (!personId) return [];
  try {
    const stored = JSON.parse(window.localStorage.getItem(key(personId)) ?? "[]");
    return Array.isArray(stored) ? stored.filter((x) => typeof x === "string").slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(personId: string | undefined, text: string): string[] {
  const value = text.trim();
  if (!personId || value.length < 2) return recentSearches(personId);
  const next = [value, ...recentSearches(personId).filter((x) => x !== value)].slice(0, LIMIT);
  try {
    window.localStorage.setItem(key(personId), JSON.stringify(next));
  } catch {
    // Private windows and full storage: the list just isn't kept.
  }
  return next;
}

export function forgetSearches(personId: string | undefined): void {
  if (!personId) return;
  try {
    window.localStorage.removeItem(key(personId));
  } catch {
    // Nothing to forget.
  }
}
