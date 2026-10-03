#!/usr/bin/env node
/**
 * Emulator set-up (ADR-061, 11b.10): signs the app in to the seeded shop (Ganesh Patil, Sharma)
 * as a person would, with the dev stack's fixed sign-in code (OTP_FIXED_CODE, 123456). Does
 * nothing if the app is signed in already. The other emulator tests start from here in CI.
 *
 * Needs: the dev stack with the seed, the app installed, its screens in English.
 *   node e2e/sign-in.mjs
 */
import { adb, manage, reporter, screen, sleep, startApp, tap, waitFor } from "./device.mjs";

const PHONE = "9876500001";
const CODE = "123456";
const DISTRIBUTOR = "Sharma Distributors";
const { check, finish } = reporter();

// Earlier runs' sign-ins count towards the hourly limit.
manage("reset_e2e_limits", "--phone", PHONE);

/** Type into a field: tap it, then send the characters. */
async function type(field, text) {
  tap(field);
  await sleep(500);
  adb("shell", "input", "text", text);
  await sleep(500);
}

startApp();
const first = await waitFor(
  (n) => n.text === "Sign in to order" || n.text.startsWith("Hello"),
  40000,
);
check(first !== null, "the app opens");
if (first?.text === "Sign in to order") {
  const phone = await waitFor((n) => n.cls.endsWith("EditText"));
  await type(phone, PHONE);
  tap(await waitFor((n) => n.label === "Send code" && n.enabled));
  const code = await waitFor((n) => n.cls.endsWith("EditText") && n.text === "", 20000);
  check(code !== null, "the app asks for the code");
  await type(code, CODE);
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
