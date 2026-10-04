#!/usr/bin/env node
/**
 * Emulator test (ADR-061 item 9; owner, checkpoint review item 7): a bill paid online from the
 * app. Account → My bills → a bill → Pay → Pay now opens the payment page in a Chrome Custom Tab;
 * the dev test gateway pays it; the page sends the shop back to the app, which shows "Paid" from
 * the server.
 *
 * Needs: the dev stack with the test gateway on for the distributor (as seeded), an emulator with
 * Chrome and the app installed and signed in to a shop with an unpaid bill, in English.
 *   node e2e/pay-online.mjs
 */
import { adb, PACKAGE, reporter, screen, sleep, startApp, tap, until, waitFor } from "./device.mjs";

const { check, finish } = reporter();
const tabs = () => {
  const all = screen().filter((n) => /^[^,]?, /u.test(n.label));
  const bottom = Math.max(...all.map((n) => n.y));
  return all.filter((n) => n.y === bottom).sort((a, b) => a.x - b.x);
};
const foreground = () =>
  /mCurrentFocus=.*\{[^}]*\s(\S+)\//.exec(adb("shell", "dumpsys", "window"))?.[1];

startApp();
await waitFor((n) => n.text.startsWith("₹"), 25000);
tap(tabs()[4]);
tap(await waitFor((n) => n.text === "My bills"));
const bill = await waitFor((n) => n.clickable && /^INV\//.test(n.label), 15000);
check(bill !== null, "My bills lists an unpaid bill");
tap(bill);
const payBill = await waitFor((n) => /^Pay ₹/.test(n.label) && !/now$/.test(n.label), 15000);
check(payBill !== null, "the bill offers Pay");
const amount = payBill.label.replace(/^Pay /, "");
tap(payBill);
const payNow = await waitFor((n) => n.label === `Pay ${amount} now`, 15000);
check(payNow !== null, `the checkout screen offers "Pay ${amount} now"`);
tap(payNow);

// The Custom Tab: Chrome in front, on the payment page (no shop menus), then the test gateway.
check(
  await until(() => foreground() === "com.android.chrome", 15000),
  "the payment page opens in Chrome",
);
// A fresh emulator's Chrome asks about an account first (a phone in use doesn't).
const firstRun = await waitFor((n) => n.text === "Use without an account", 5000);
if (firstRun) {
  tap(firstRun);
  await sleep(1500);
}
const pagePay = await waitFor(
  (n) => n.text === `Pay ${amount} now` || n.label === `Pay ${amount} now`,
  20000,
);
check(pagePay !== null, "the payment page shows the same amount");
check(
  !screen().some((n) => n.text === "Catalog" || n.text === "My account"),
  "no shop menus on it",
);
tap(pagePay);
const gatewayPay = await waitFor(
  (n) => (n.text === "Pay" || n.label === "Pay") && n.clickable,
  20000,
);
check(gatewayPay !== null, "the test gateway's page opens");
tap(gatewayPay);
const back = await waitFor(
  (n) => n.text === "Back to the app" || n.label === "Back to the app",
  20000,
);
check(back !== null, "the gateway says paid");
tap(back);

// Back on the payment page: paid, and it returns to the app by itself.
check(await until(() => foreground() === PACKAGE, 20000), "the shop is back in the app");
const paid = await waitFor((n) => n.text === "Paid", 20000);
check(paid !== null, "the app shows Paid, read from the server");
check(
  screen().some((n) => n.label === "Download receipt"),
  "with the receipt",
);
await sleep(500);
finish(`Paid ${amount} online from the app.`);
