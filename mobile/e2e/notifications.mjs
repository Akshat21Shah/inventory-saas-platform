#!/usr/bin/env node
/**
 * Emulator test (owner, checkpoint review item 3): the bell with the unread count in the header,
 * the notifications screen, and a tapped message opening its page, marked read.
 *
 * Needs: the app signed in to a shop with unread messages, in English (`adb devices`).
 *   node e2e/notifications.mjs
 */
import { adb, reporter, screen, sleep, startApp, tap, waitFor } from "./device.mjs";

const { check, finish } = reporter();
const unreadOf = (label) => Number(/(\d+) unread/.exec(label)?.[1] ?? 0);

startApp();
await waitFor((n) => n.text.startsWith("Hello"), 25000);
const bell = await waitFor((n) => /^Notifications/.test(n.label), 10000);
check(bell !== null, "the header has the bell");
const before = unreadOf(bell?.label ?? "");
check(before > 0, `the bell says how many are unread (${before})`);
tap(bell);
check((await waitFor((n) => n.text === "Mark all as read", 10000)) !== null, "Notifications open");
const item = await waitFor((n) => n.clickable && /\(Unread\)$/.test(n.label), 10000);
check(item !== null, "an unread message stands out");
const title = item.label.replace(/ \(Unread\)$/, "");
tap(item);
// Its page: an order, a bill or payments.
const page = await waitFor(
  (n) => /^(ORD-|Bill |My payments|My bills)/.test(n.text) && n.y < 600,
  15000,
);
check(page !== null, `"${title}" opens its page (${page?.text ?? "nothing"})`);
adb("shell", "input", "keyevent", "4");
await sleep(2500);
const after = unreadOf((await waitFor((n) => /^Notifications/.test(n.label), 10000))?.label ?? "");
check(after === before - 1, `the bell counts one fewer (${before} → ${after})`);
const read = screen().find((n) => n.label === title || n.label === `${title} (Unread)`);
check(read?.label === title, "the message is now read");
finish("The bell, the inbox and a tapped message work.");
