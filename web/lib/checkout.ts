"use client";

import { newIdempotencyKey } from "@/lib/idempotency";

/**
 * One checkout attempt = one Idempotency-Key (ADR-044): created on the first "Place order" for a
 * cart, kept (across reloads) until the order is placed or the cart changes, and reused by every
 * retry, so a dropped connection can never create a second order. Stored per sign-in in
 * localStorage; a missing or blocked storage just means a fresh key after a reload.
 */
export interface Attempt {
  key: string;
  /** The cart it was made for (products and quantities, address, note). */
  cart: string;
  startedAt: number;
}

const STORAGE_KEY = "shop.checkout-attempt";

function read(owner: string): Attempt | null {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_KEY}:${owner}`);
    return raw ? (JSON.parse(raw) as Attempt) : null;
  } catch {
    return null;
  }
}

function write(owner: string, attempt: Attempt | null) {
  try {
    const key = `${STORAGE_KEY}:${owner}`;
    if (attempt) window.localStorage.setItem(key, JSON.stringify(attempt));
    else window.localStorage.removeItem(key);
  } catch {
    // storage unavailable: the attempt lives only in memory
  }
}

/** The attempt for this cart: the stored one if the cart is unchanged, else a new one. */
export function attemptFor(owner: string, cart: string): Attempt {
  const stored = read(owner);
  if (stored && stored.cart === cart) return stored;
  const attempt = { key: newIdempotencyKey(), cart, startedAt: Date.now() };
  write(owner, attempt);
  return attempt;
}

/** An attempt left over from before a reload (its result may be unknown). */
export function pendingAttempt(owner: string): Attempt | null {
  return read(owner);
}

export function finishAttempt(owner: string) {
  write(owner, null);
}
