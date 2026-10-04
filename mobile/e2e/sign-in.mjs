#!/usr/bin/env node
/**
 * Emulator set-up (ADR-061, 11b.10): signs the app in to the seeded shop (Ganesh Patil, Sharma)
 * as a person would, with the dev stack's fixed sign-in code (OTP_FIXED_CODE, 123456). Does
 * nothing if the app is signed in already. The other emulator tests start from here in CI.
 *
 * Needs: the dev stack with the seed, the app installed, its screens in English.
 *   node e2e/sign-in.mjs
 */
import {
  adb,
  keyboardShown,
  manage,
  reporter,
  screen,
  sleep,
  startApp,
  tap,
  until,
  waitFor,
} from "./device.mjs";

const PHONE = "9876500001";
const CODE = "123456";
const DISTRIBUTOR = "Sharma Distributors";
const { check, finish } = reporter();

// Earlier runs' sign-ins count towards the hourly limit.
manage("reset_e2e_limits", "--phone", PHONE);

/** Type digits into a field and check they arrived: a slow phone can drop the first key while
 * the field takes focus. Closes the keyboard after, as it can cover the button below. */
async function type(find, digits) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const field = await waitFor(find, 90000);
    if (!field) return false;
    tap(field);
    await until(keyboardShown, 5000);
    adb("shell", "input", "keyevent", ...Array(14).fill("KEYCODE_DEL"));
    adb("shell", "input", "text", digits);
    await sleep(800);
    const typed = screen().find(find)?.text.replace(/\D/g, "");
    if (keyboardShown()) adb("shell", "input", "keyevent", "KEYCODE_BACK");
    await sleep(500);
    if (typed === digits) return true;
  }
  return false;
}

startApp();
const first = await waitFor(
  (n) => n.text === "Sign in to order" || n.text.startsWith("Hello"),
  90000, // a cold start on CI's software-drawn emulator is slow
);
check(first !== null, "the app opens");
if (first?.text === "Sign in to order") {
  const field = (n) => n.cls.endsWith("EditText");
  check(await type(field, PHONE), "the mobile number is typed");
  tap(await waitFor((n) => n.label === "Send code" && n.enabled));
  // While "Resend in …" counts down, the screen can't be read (device.mjs `screen`).
  check(
    (await waitFor((n) => n.text === "6-digit code", 90000)) !== null,
    "the app asks for the code",
  );
  check(await type(field, CODE), "the code is typed");
  tap(await waitFor((n) => n.label === "Sign in" && n.enabled));
  // A number with several distributors chooses one.
  const next = await waitFor((n) => n.text === DISTRIBUTOR || n.text.startsWith("Hello"), 30000);
  if (next?.text === DISTRIBUTOR) tap(next);
}
check(
  (await waitFor((n) => n.text.startsWith("Hello"), 40000)) !== null,
  `signed in to ${DISTRIBUTOR}`,
);
check(!screen().some((n) => n.text === "Sign in to order"), "the sign-in screen is gone");
finish("Signed in.");
