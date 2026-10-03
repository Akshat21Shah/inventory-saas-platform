#!/usr/bin/env node
/**
 * Emulator test (owner, checkpoint review): typing a whole word into search keeps the keyboard
 * open and the box focused while the results update; Search closes the keyboard and keeps the
 * text.
 *
 * Needs: a running emulator (or USB phone) with the app installed and signed in (`adb devices`).
 *   node e2e/search-keyboard.mjs [word]          (default: "biscuit")
 */
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const ADB = process.env.ADB ?? join(homedir(), "Library/Android/sdk/platform-tools/adb");
const PACKAGE = process.env.APP_ID ?? "com.example.shop";
const WORD = process.argv[2] ?? "biscuit";
const PAUSE_MS = 700; // longer than the search's 250 ms pause, so results render between letters

const adb = (...args) => execFileSync(ADB, args, { encoding: "utf8" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function keyboardShown() {
  return /mInputShown=true/.test(adb("shell", "dumpsys", "input_method"));
}

/** The search box: the screen's first focusable EditText with a hint (by class and attributes,
 * so the app's language doesn't matter; the box's container also reports as an EditText). */
function searchBox() {
  adb("shell", "uiautomator", "dump", "/sdcard/search-test.xml");
  const xml = adb("exec-out", "cat", "/sdcard/search-test.xml");
  const node = (xml.match(/<node [^>]*class="android\.widget\.EditText"[^>]*>/g) ?? []).find(
    (n) => /focusable="true"/.test(n) && /hint="[^"]+"/.test(n),
  );
  if (!node) return null;
  const attr = (name) => new RegExp(`${name}="([^"]*)"`).exec(node)?.[1] ?? "";
  return { text: attr("text"), focused: attr("focused") === "true", hint: attr("hint"), xml };
}

const failures = [];
function check(ok, what) {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failures.push(what);
}

async function until(test, ms = 8000) {
  for (const started = Date.now(); Date.now() - started < ms;) {
    if (test()) return true;
    await sleep(400);
  }
  return false;
}

// From a fresh start: home, then a tap on the search box, as a shop would do it.
adb("shell", "am", "force-stop", PACKAGE);
adb("shell", "am", "start", "-W", "-n", `${PACKAGE}/.MainActivity`);
const entry = await (async () => {
  for (let i = 0; i < 20; i++) {
    adb("shell", "uiautomator", "dump", "/sdcard/search-test.xml");
    const xml = adb("exec-out", "cat", "/sdcard/search-test.xml");
    // The home screen's search entry: reported as a clickable EditText without a hint (the
    // search screen's real input has one).
    const node = (xml.match(/<node [^>]*class="android\.widget\.EditText"[^>]*>/g) ?? []).find(
      (n) => /clickable="true"/.test(n) && /hint=""/.test(n),
    );
    if (node && /₹/.test(xml)) return node;
    await sleep(700);
  }
  return null;
})();
check(entry !== null, "home shows the search box");
const [x1, y1, x2, y2] = (/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/.exec(entry ?? "") ?? [])
  .slice(1)
  .map(Number);
adb("shell", "input", "tap", String(Math.round((x1 + x2) / 2)), String(Math.round((y1 + y2) / 2)));
check(await until(keyboardShown), "tapping it opens search with the keyboard up");
let box = searchBox();
// An empty input is reported with its hint as its text.
check(
  Boolean(box?.focused) && (box?.text === "" || box?.text === box?.hint),
  "the search box is focused and empty",
);

let typed = "";
for (const letter of WORD) {
  adb("shell", "input", "text", letter);
  typed += letter;
  await sleep(PAUSE_MS);
  box = searchBox();
  const shown = box?.text === typed || box?.text === typed.replace(/./, (c) => c.toUpperCase());
  check(keyboardShown(), `"${typed}": the keyboard is still open`);
  check(Boolean(box?.focused), `"${typed}": the box keeps the focus`);
  check(shown, `"${typed}": the box shows the typed text (got "${box?.text ?? ""}")`);
}

await sleep(1500);
box = searchBox();
// Products on screen, counted by their prices (any language).
const results = (box?.xml.match(/text="₹[^"]*"/g) ?? []).length;
check(results > 0, `results for "${WORD}" are on screen (${results} prices)`);
check(keyboardShown(), "the keyboard is still open after the results arrived");

adb("shell", "input", "keyevent", "66"); // Enter / Search
await sleep(1200);
check(!keyboardShown(), "Search closes the keyboard");
check(searchBox()?.text?.toLowerCase() === WORD.toLowerCase(), "the typed word stays in the box");

if (failures.length) {
  console.error(`\n${failures.length} check(s) failed.`);
  process.exit(1);
}
console.log(`\nAll checks passed for "${WORD}".`);
