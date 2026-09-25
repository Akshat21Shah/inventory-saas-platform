export { cn } from "cn";

/** A copy of `record` without `key` (for clearing one field's error, one draft value...). */
export function omitKey<T extends Record<string, unknown>>(record: T, key: string): T {
  const copy = { ...record };
  delete copy[key];
  return copy;
}
