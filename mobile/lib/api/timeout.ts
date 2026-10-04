/** No request waits forever on a weak connection (ADR-061 item 10): after this it fails as a lost
 * connection, so screens show what was saved and the cart keeps its changes. */
export const REQUEST_TIMEOUT_MS = 20_000;

/** Runs `request` with a signal that aborts after the time limit, or when `outer` (TanStack
 * Query's, when a screen goes away) aborts. */
export async function withTimeout<T>(
  outer: AbortSignal | null | undefined,
  request: (signal: AbortSignal) => Promise<T>,
  ms = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  const stop = () => controller.abort();
  if (outer?.aborted) controller.abort();
  outer?.addEventListener("abort", stop);
  try {
    return await request(controller.signal);
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", stop);
  }
}
