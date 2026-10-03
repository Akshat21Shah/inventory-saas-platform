#!/usr/bin/env node
/**
 * Emulator test (owner, checkpoint review; spec: at most ~3 taps from search to a placed order):
 * from search results, Add, the cart in the bottom bar, and Place order, and the order is placed.
 * Places a real order on the dev stack. Needs the app signed in with the shop's language English.
 *   node e2e/three-taps.mjs [word]     (default: "glucose")
 */
import { adb, keyboardShown, reporter, sleep, startApp, tap, until, waitFor } from "./device.mjs";

const WORD = process.argv[2] ?? "glucose";
const { check, finish } = reporter();
const price = (n) => n.text.startsWith("₹");

// Setup (not counted): an empty cart, then search results.
startApp();
check(Boolean(await waitFor(price, 20000)), "the app opens signed in");
tap(await waitFor((n) => /, Cart$/.test(n.label) || n.label === "Cart"));
let clear = await waitFor((n) => n.label === "Clear cart", 3000);
for (
  let i = 0;
  !clear &&
  i < 6 &&
  (await waitFor((n) => n.label === "Your cart" || n.text === "Your cart", 2000));
  i++
) {
  adb("shell", "input", "swipe", "540", "1700", "540", "700", "300");
  clear = await waitFor((n) => n.label === "Clear cart", 1500);
}
if (clear) {
  tap(clear);
  tap(await waitFor((n) => n.text.toUpperCase() === "CLEAR CART" && n.cls.endsWith("Button")));
  await sleep(1500);
}
tap(await waitFor((n) => /, Home$/.test(n.label) || n.label === "Home"));
tap(await waitFor((n) => n.cls.endsWith("EditText") && n.clickable && n.hint === ""));
await waitFor((n) => n.cls.endsWith("EditText") && n.focused);
adb("shell", "input", "text", WORD);
await waitFor((n) => n.text.startsWith("₹"), 15000);
adb("shell", "input", "keyevent", "66"); // the keyboard's Search key: searching, not one of the taps
check(await until(() => !keyboardShown()), "Search closes the keyboard over the results");
const add = await waitFor((n) => /^Add .+ to cart$/.test(n.label) && n.enabled, 15000);
check(Boolean(add), `search results for "${WORD}" have an Add button`);

// The three taps.
let taps = 0;
tap(add);
taps++;
await sleep(1200); // the quantity goes to the server after a short pause
tap(await waitFor((n) => /, Cart$/.test(n.label)));
taps++;
const place = await waitFor((n) => /^Place order · ₹/.test(n.label) && n.enabled, 15000);
check(Boolean(place), "the cart offers Place order");
tap(place);
taps++;
const placed = await waitFor((n) => /^ORD-\d{4}-\d+$/.test(n.text), 20000);
check(Boolean(placed), `the order is placed (${placed?.text ?? "no order"})`);
check(taps === 3, `${taps} taps from search results to a placed order`);
finish(`Search to a placed order in ${taps} taps.`);
