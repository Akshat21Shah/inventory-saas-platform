/** What the emulator tests share: adb, the screen's elements, taps and waits. */
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ADB = process.env.ADB ?? join(homedir(), "Library/Android/sdk/platform-tools/adb");
export const PACKAGE = process.env.APP_ID ?? "com.example.shop";
export const SCHEME = process.env.APP_SCHEME ?? "shopapp";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

export const adb = (...args) => execFileSync(ADB, args, { encoding: "utf8" });

/** A management command in the dev stack's backend (`manage.py …`); its output. */
export const manage = (...args) =>
  execFileSync(
    "docker",
    ["compose", "-f", join(REPO, "infra/docker-compose.yml"), "exec", "-T", "backend"].concat([
      "python",
      "manage.py",
      ...args,
    ]),
    { encoding: "utf8" },
  );
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Every element on screen, with its attributes. While something on the screen keeps changing (a
 * countdown, a loading animation), Android's dump waits about 10 s, says "could not get idle
 * state" and writes nothing; reading the file then gave the screen before (the "stale dump" seen
 * on Android 11). The old file goes first, so an unreadable screen comes back empty, never stale.
 */
export function screen() {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const said = adb("shell", "rm -f /sdcard/e2e.xml; uiautomator dump /sdcard/e2e.xml 2>&1");
    if (!/dumped to/.test(said)) continue;
    const nodes = parse(adb("exec-out", "cat", "/sdcard/e2e.xml"));
    // A slow emulator's "Pixel Launcher isn't responding" covers the app, and the dump reads
    // only the dialog: "Wait" (safe whichever app it names), then read again.
    const wait = nodes.some((n) => /isn.t responding$/.test(n.text))
      ? nodes.find((n) => n.text === "Wait")
      : null;
    if (!wait) return nodes;
    tap(wait);
    execFileSync("sleep", ["1"]);
  }
  return [];
}

function parse(xml) {
  return (xml.match(/<node [^>]*>/g) ?? []).map((raw) => {
    const attr = (name) => new RegExp(` ${name}="([^"]*)"`).exec(raw)?.[1] ?? "";
    const [x1, y1, x2, y2] = (/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/.exec(raw) ?? [])
      .slice(1)
      .map(Number);
    return {
      raw,
      text: attr("text"),
      label: attr("content-desc"),
      cls: attr("class"),
      hint: attr("hint"),
      focused: attr("focused") === "true",
      focusable: attr("focusable") === "true",
      clickable: attr("clickable") === "true",
      enabled: attr("enabled") !== "false",
      x: Math.round((x1 + x2) / 2),
      y: Math.round((y1 + y2) / 2),
      bounds: { x1, y1, x2, y2 },
    };
  });
}

export async function waitFor(predicate, ms = 10000) {
  for (const started = Date.now(); Date.now() - started < ms;) {
    const found = screen().find(predicate);
    if (found) return found;
    await sleep(500);
  }
  return null;
}

/** Wait until a condition on the device holds. */
export async function until(test, ms = 8000) {
  for (const started = Date.now(); Date.now() - started < ms;) {
    if (test()) return true;
    await sleep(400);
  }
  return false;
}

export function tap(node) {
  adb("shell", "input", "tap", String(node.x), String(node.y));
}

export function keyboardShown() {
  return /mInputShown=true/.test(adb("shell", "dumpsys", "input_method"));
}

/** Open one of the app's screens by its link (`/shop/orders/…`), as a tapped link would. */
export function openLink(path) {
  adb(
    "shell",
    "am",
    "start",
    "-W",
    "-a",
    "android.intent.action.VIEW",
    "-d",
    `${SCHEME}:/${path}`,
    PACKAGE,
  );
}

/** The screen's density: pixels per dp. */
export function pixelsPerDp() {
  const found = /(\d+)\s*$/.exec(adb("shell", "wm", "density").trim());
  return Number(found?.[1] ?? 160) / 160;
}

export function saveScreenshot(file) {
  writeFileSync(file, execFileSync(ADB, ["exec-out", "screencap", "-p"]));
}

export function startApp() {
  adb("shell", "am", "force-stop", PACKAGE);
  adb("shell", "am", "start", "-W", "-n", `${PACKAGE}/.MainActivity`);
}

export function reporter() {
  const failures = [];
  return {
    check(ok, what) {
      console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
      if (!ok) failures.push(what);
      return ok;
    },
    finish(summary) {
      if (failures.length) {
        console.error(`\n${failures.length} check(s) failed.`);
        process.exit(1);
      }
      console.log(`\n${summary}`);
    },
  };
}

/** Test set-up: open the Cart tab and clear it (English). */
export async function emptyCart() {
  tap(await waitFor((n) => /, Cart$/.test(n.label) || n.label === "Cart"));
  const found = (n) => n.label === "Empty the cart" || n.text === "Your cart is empty";
  let node = await waitFor(found, 4000);
  for (let i = 0; !node && i < 8; i++) {
    adb("shell", "input", "swipe", "540", "1700", "540", "700", "300");
    node = await waitFor(found, 1500);
  }
  if (node?.label === "Empty the cart") {
    tap(node);
    // Android's confirm dialog, its button in capitals.
    tap(
      await waitFor((n) => n.text.toUpperCase() === "EMPTY THE CART" && n.cls.endsWith("Button")),
    );
    await waitFor((n) => n.text === "Your cart is empty", 8000);
  }
}
