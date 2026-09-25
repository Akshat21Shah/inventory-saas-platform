import { ADMIN, FULL_STACK, resetLimits, SHOP_PHONES } from "./support/stack";

/** Full-stack runs start from clean rate-limit counters, so they can run back to back. */
export default function globalSetup() {
  if (FULL_STACK) resetLimits({ emails: [ADMIN.email], phones: SHOP_PHONES });
}
