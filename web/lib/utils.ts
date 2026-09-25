export { cn } from "cn";

/** A copy of `record` without `key` (for clearing one field's error, one draft value...). */
export function omitKey<T extends Record<string, unknown>>(record: T, key: string): T {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

/** "+919876543210" → "+91 98765 43210" for display; anything else is returned unchanged. */
export function formatIndianMobile(phone: string): string {
  const match = /^\+91(\d{5})(\d{5})$/.exec(phone);
  return match ? `+91 ${match[1]} ${match[2]}` : phone;
}
