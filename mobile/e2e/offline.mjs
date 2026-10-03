#!/usr/bin/env node
/**
 * Emulator test (ADR-061 item 10): the app without a connection. With the phone in airplane mode
 * the app still opens signed in, shows what was saved and says so, prices read "as last seen",
 * the cart takes changes, and "Place order" waits for the connection; back online, the change
 * reaches the server.
 *
 * Needs: the app signed in to a shop, in English, with an empty cart (`adb devices`). Turns
 * airplane mode on and off.
 *   node e2e/offline.mjs
 */
import { adb, emptyCart, reporter, screen, sleep, startApp, tap, waitFor } from "./device.mjs";

const { check, finish } = reporter();
const tabs = () => {
  const all = screen().filter((n) => /^[^,]?, /u.test(n.label));
  const bottom = Math.max(...all.map((n) => n.y));
  return all.filter((n) => n.y === bottom).sort((a, b) => a.x - b.x);
};
const airplane = (on) =>
  adb("shell", "cmd", "connectivity", "airplane-mode", on ? "enable" : "disable");

try {
  // Online first: home and the catalogue are seen, so they are saved.
  airplane(false);
  startApp();
  await waitFor((n) => n.text.startsWith("Hello"), 25000);
  await emptyCart();
  tap(tabs()[1]);
  await waitFor((n) => n.text.startsWith("₹"), 15000);
  tap(tabs()[0]);
  await sleep(5000); // the saved copy is written a few seconds after a change

  airplane(true);
  await sleep(2000);
  startApp();
  check(
    (await waitFor((n) => n.text.startsWith("Hello"), 25000)) !== null,
    "with no connection the app opens signed in",
  );
  check(
    (await waitFor(
      (n) => n.text.startsWith("You're offline. Showing what was saved at"),
      10000,
    )) !== null,
    'it says "You\'re offline. Showing what was saved at …"',
  );
  tap(tabs()[1]);
  check(
    (await waitFor((n) => n.text.startsWith("₹"), 10000)) !== null,
    "the saved catalogue shows",
  );
  check(
    screen().some((n) => n.text === "as last seen"),
    'prices read "as last seen"',
  );
  const add = await waitFor((n) => /^Add .+ to cart$/.test(n.label) && n.enabled, 10000);
  check(add !== null, "a product can be added offline");
  const product = add.label.replace(/^Add (.+) to cart$/, "$1");
  tap(add);
  await sleep(1000);
  tap(tabs()[2]);
  check(
    (await waitFor((n) => n.text.startsWith("Your cart is saved on this phone"), 10000)) !== null,
    "the cart says it's saved on the phone",
  );
  check(
    screen().some((n) => n.text === product),
    `"${product}" is in the cart, waiting to be sent`,
  );
  const place = await waitFor((n) => /^Place order/.test(n.label), 10000);
  check(place !== null && !place.enabled, '"Place order" waits for the connection');
  check(
    screen().some((n) => n.text.startsWith("Needs internet")),
    "and says it needs internet",
  );

  airplane(false);
  check(
    (await waitFor((n) => n.label === `Fewer ${product}` || n.text === product, 30000)) !== null &&
      (await waitFor((n) => /^Place order/.test(n.label) && n.enabled, 30000)) !== null,
    "back online, the change reaches the server and the order can be placed",
  );
} finally {
  airplane(false);
}
finish("The app works without a connection.");
