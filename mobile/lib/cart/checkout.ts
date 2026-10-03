/**
 * One checkout attempt = one Idempotency-Key (ADR-044, ADR-061 item 10), the app's twin of
 * `web/lib/checkout.ts`: made on the first "Place order" for a cart, kept on the phone (across
 * restarts) until the order is placed or the cart changes, and reused by every retry, so a dropped
 * connection can never create a second order.
 */
import * as SecureStore from "expo-secure-store";

import { newIdempotencyKey } from "@/lib/shared/idempotency";

export interface Attempt {
  key: string;
  /** The cart it was made for (products and quantities, address, note). */
  cart: string;
  startedAt: number;
}

const storageKey = (owner: string) => `checkout-attempt.${owner.replace(/[^\w.-]/g, "")}`;

async function read(owner: string): Promise<Attempt | null> {
  const raw = await SecureStore.getItemAsync(storageKey(owner));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Attempt;
  } catch {
    return null;
  }
}

export async function attemptFor(owner: string, cart: string): Promise<Attempt> {
  const stored = await read(owner);
  if (stored && stored.cart === cart) return stored;
  const attempt = { key: newIdempotencyKey(), cart, startedAt: Date.now() };
  await SecureStore.setItemAsync(storageKey(owner), JSON.stringify(attempt));
  return attempt;
}

/** An attempt left from before the app was closed (its result may be unknown). */
export function pendingAttempt(owner: string): Promise<Attempt | null> {
  return read(owner);
}

export async function finishAttempt(owner: string): Promise<void> {
  await SecureStore.deleteItemAsync(storageKey(owner));
}
