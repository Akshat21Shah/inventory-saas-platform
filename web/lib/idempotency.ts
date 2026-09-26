/** A fresh Idempotency-Key (ADR-005): a repeated request with the same key returns the first
 * result, so a double tap or a retry after a dropped connection never posts twice.
 * `crypto.getRandomValues` works on plain http too (phones on the LAN), unlike `randomUUID`. */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function idempotent(key: string): RequestInit {
  return { headers: { "Idempotency-Key": key } };
}
