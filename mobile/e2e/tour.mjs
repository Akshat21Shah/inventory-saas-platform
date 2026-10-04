#!/usr/bin/env node
/**
 * Emulator test (ADR-061, 11b.10): every screen of the app in English, Hindi and Marathi, as the
 * web's responsive check does for the web. For each language it chooses the language on Your
 * profile, opens every screen by its link, scrolls it to the end and checks:
 * - no text shows as its key (`shop.money.statement`);
 * - in Hindi and Marathi, no text the app has translated shows in English;
 * - every button and link is at least 44 × 44 dp (a target cut by the scrolling edge is skipped).
 * It saves a screenshot of every screen in each position (e2e/screenshots/<phone>/<language>/),
 * for a person to look at the words: cut-off text can't be read from the screen's elements.
 *
 * Needs: the dev stack with the seed (`make up`, `make seed`), the app installed and signed in to
 * the seeded shop (Ganesh Patil, Sharma; `e2e/sign-in.mjs`). Ends in English. Two phones at once
 * need two shops, as the language is the person's: SHOP_PHONE=9876500000 (Omkar Joshi) for one.
 *   node e2e/tour.mjs                 # en, hi, mr
 *   LANGUAGES=hi node e2e/tour.mjs    # one language
 *   ANDROID_SERIAL=emulator-5556 …    # one phone of several
 */
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  adb,
  manage,
  openLink,
  pixelsPerDp,
  reporter,
  saveScreenshot,
  screen,
  sleep,
  startApp,
  tap,
  until,
  waitFor,
} from "./device.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOBILE = join(HERE, "..");
const json = (path) => JSON.parse(readFileSync(join(MOBILE, path), "utf8"));
const { check, finish } = reporter();

// --- The texts, as the app merges them (lib/i18n/messages.ts) --------------------------------------

function flatten(tree, prefix = "", out = {}) {
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out[path] = value;
    else flatten(value, path, out);
  }
  return out;
}
const texts = (code) => ({
  ...flatten(json(`messages/web/${code}.json`)),
  ...flatten(json(`messages/app/${code}.json`), "app"),
});
const english = texts("en");
const NAMESPACES = new Set(Object.keys(english).map((key) => key.split(".")[0]));
const LANGUAGES = json("lib/shared/languages.json").languages;
const chosen = (process.env.LANGUAGES ?? "en,hi,mr").split(",");
/** Only some screens, by name (`ONLY=profile,messages`); every screen when unset. */
const only = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;

/** A text shown as its key: `shop.money.statement`, or use-intl's `namespace.key` fallback. */
const looksLikeKey = (text) =>
  /^[a-zA-Z]+(\.[\w-]+)+$/.test(text) && NAMESPACES.has(text.split(".")[0]);

/** English texts that, in `code`, have other words: shown in English, they weren't switched.
 * Texts with values ({name}) are left out: what shows isn't the text as written. So are single
 * words: a distributor's own names ("Live", "Food") may match one. */
function untranslated(code) {
  if (code === "en") return new Set();
  const own = texts(code);
  const ownValues = new Set(Object.values(own));
  return new Set(
    Object.entries(english)
      .filter(([, text]) => !text.includes("{") && /[a-z]{3}/i.test(text) && /\S\s+\S/.test(text))
      .filter(([key, text]) => own[key] && own[key] !== text && !ownValues.has(text))
      .map(([, text]) => text),
  );
}

// --- The screens --------------------------------------------------------------------------------

const links = JSON.parse(
  manage("e2e_shop_links", "--phone", process.env.SHOP_PHONE ?? "9876500001"),
);
const SCREENS = [
  ["home", "/shop"],
  ["catalog", "/shop/catalog"],
  ["category", links.category],
  ["product", links.product],
  ["search", "/shop/search?q=a"],
  ["cart", "/shop/cart"],
  ["orders", "/shop/orders"],
  ["order", links.order],
  ["notifications", "/shop/notifications"],
  ["account", "/shop/account"],
  ["profile", "/shop/account/profile"],
  ["messages", "/shop/account/messages"],
  ["addresses", "/shop/account/addresses"],
  ["help", "/shop/account/help"],
  ["privacy", "/shop/account/privacy"],
  ["suggest", "/shop/account/suggest"],
  ["bills", "/shop/invoices"],
  ["bill", links.bill],
  ["return", links.bill && `${links.bill}/return`],
  ["statement", "/shop/statement"],
  ["payments", "/shop/payments"],
  ["returns", "/shop/returns"],
];
for (const [name, path] of SCREENS) check(Boolean(path), `the seed has a ${name} to open`);

// --- On the phone ------------------------------------------------------------------------------

// The emulator's name (Android 12 and up keep it in ro.boot…, Android 11 in ro.kernel…).
const phone =
  adb("shell", "getprop", "ro.boot.qemu.avd_name").trim() ||
  adb("shell", "getprop", "ro.kernel.qemu.avd_name").trim() ||
  adb("get-serialno").trim();
const perDp = pixelsPerDp();
const [width, height] = adb("shell", "wm", "size").trim().split(/\s+/).pop().split("x").map(Number);
const SHOTS = join(HERE, "screenshots", phone);

const signature = (nodes) => nodes.map((n) => `${n.text}|${n.label}|${n.y}`).join("\n");

/** The screen once it stops changing (data loaded, skeletons gone). */
async function settled(ms = 15000) {
  let before = "";
  let nodes = [];
  for (const started = Date.now(); Date.now() - started < ms;) {
    await sleep(700);
    nodes = screen();
    const now = signature(nodes);
    if (now === before && nodes.some((n) => n.text)) return nodes;
    before = now;
  }
  return nodes;
}

/** Back to the top of a screen: a tab opened by its link keeps where it was scrolled. */
async function toTop() {
  let before = signature(screen());
  for (let i = 0; i < 10; i++) {
    adb(
      "shell",
      "input",
      "swipe",
      String(width / 2),
      String(height * 0.3),
      String(width / 2),
      String(height * 0.85),
      "150",
    );
    await sleep(600);
    const now = signature(screen());
    if (now === before) return;
    before = now;
  }
}

/** Tap targets under 44 × 44 dp, leaving out one cut by the edge of the part that scrolls and one
 * inside a big enough target (a switch in a row that is all one target). */
function smallTargets(nodes) {
  const min = 44 * perDp - 2; // rounding to whole pixels
  const scrolling = nodes.filter((n) => /ScrollView|RecyclerView/.test(n.cls)).map((n) => n.bounds);
  const cut = ({ y1, y2 }) =>
    scrolling.some((s) => y1 >= s.y1 && y2 <= s.y2 && (y1 <= s.y1 + 1 || y2 >= s.y2 - 1));
  const small = ({ x1, y1, x2, y2 }) => x2 - x1 < min || y2 - y1 < min;
  const targets = nodes.filter((n) => n.clickable && n.enabled);
  const inside = (b) =>
    targets.some(
      ({ bounds: o }) =>
        o !== b &&
        (!small(o) || cut(o)) &&
        o.x1 <= b.x1 &&
        o.y1 <= b.y1 &&
        o.x2 >= b.x2 &&
        o.y2 >= b.y2,
    );
  return targets.filter((n) => small(n.bounds) && !cut(n.bounds) && !inside(n.bounds));
}

async function chooseLanguage(code) {
  const { native } = LANGUAGES.find((language) => language.code === code);
  openLink("/shop/account/profile");
  // On a small phone the choice is below the fold, and the dump lists only what's visible.
  let option = await waitFor((n) => n.text === native, 8000);
  for (let i = 0; !option && i < 4; i++) {
    adb(
      "shell",
      "input",
      "swipe",
      String(width / 2),
      String(height * 0.7),
      String(width / 2),
      String(height * 0.3),
      "400",
    );
    option = await waitFor((n) => n.text === native, 3000);
  }
  if (!option) return false;
  tap(option);
  // The app switches at once: the tab bar's "Home" is in the new language.
  const home = texts(code)["nav.home"];
  return (await waitFor((n) => n.label.endsWith(home) || n.text === home, 15000)) !== null;
}

async function tour(code) {
  const dir = join(SHOTS, code);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const inEnglish = untranslated(code);
  let last = null; // the screen toured before
  for (const [index, [name, path]] of SCREENS.entries()) {
    if (!path || (only && !only.has(name))) continue;
    const started = Date.now();
    openLink(path);
    const keys = new Set();
    const leftInEnglish = new Set();
    const small = new Set();
    // The checks wait for this screen's own elements (not the screen before).
    const fresh = await until(() => {
      const now = signature(screen());
      return now !== "" && now !== last;
    }, 20000);
    await toTop();
    let nodes = await settled();
    // A screen that never stops changing can't be read (device.mjs `screen`).
    check(fresh && nodes.length > 0, `${code} ${name}: the screen's elements can be read`);
    if (nodes.length === 0) continue;
    for (let part = 1, before = ""; part <= 4; part++) {
      const shot = `${String(index + 1).padStart(2, "0")}-${name}${part > 1 ? `-${part}` : ""}.png`;
      saveScreenshot(join(dir, shot));
      for (const n of nodes) {
        for (const text of [n.text, n.label]) {
          if (looksLikeKey(text)) keys.add(text);
          if (inEnglish.has(text)) leftInEnglish.add(text);
        }
      }
      for (const n of smallTargets(nodes)) small.add(n.label || n.text || n.cls);
      // Scroll on, until the screen no longer moves.
      before = signature(nodes);
      adb(
        "shell",
        "input",
        "swipe",
        String(width / 2),
        String(height * 0.7),
        String(width / 2),
        String(height * 0.3),
        "400",
      );
      await sleep(900);
      nodes = screen();
      if (signature(nodes) === before) break;
    }
    last = signature(nodes);
    console.log(`     ${code} ${name}: ${Math.round((Date.now() - started) / 1000)} s`);
    check(keys.size === 0, `${code} ${name}: no text shows as its key ${[...keys].join(", ")}`);
    check(
      leftInEnglish.size === 0,
      `${code} ${name}: nothing left in English ${[...leftInEnglish].join(" | ")}`,
    );
    check(
      small.size === 0,
      `${code} ${name}: every target is 44 dp or more ${[...small].join(" | ")}`,
    );
  }
}

startApp();
await waitFor((n) => n.text.startsWith("₹") || n.text.includes("₹"), 30000);
try {
  for (const code of chosen) {
    check(await chooseLanguage(code), `the app switches to ${code}`);
    await tour(code);
  }
} finally {
  await chooseLanguage("en");
}
finish(
  `Every screen in ${chosen.join(", ")} on ${phone} (${width}×${height}); screenshots in e2e/screenshots/${phone}/.`,
);
