/** What the emulator tests share: adb, the screen's elements, taps and waits. */
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const ADB = process.env.ADB ?? join(homedir(), "Library/Android/sdk/platform-tools/adb");
export const PACKAGE = process.env.APP_ID ?? "com.example.shop";

export const adb = (...args) => execFileSync(ADB, args, { encoding: "utf8" });
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Every element on screen, with its attributes. */
export function screen() {
  adb("shell", "uiautomator", "dump", "/sdcard/e2e.xml");
  const xml = adb("exec-out", "cat", "/sdcard/e2e.xml");
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
      clickable: attr("clickable") === "true",
      enabled: attr("enabled") !== "false",
      x: Math.round((x1 + x2) / 2),
      y: Math.round((y1 + y2) / 2),
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
