#!/usr/bin/env node
/**
 * Emulator test (owner, checkpoint review): typing a whole word into search keeps the keyboard
 * open and the box focused while the results update; Search closes the keyboard and keeps the
 * text.
 *
 * Needs: a running emulator (or USB phone) with the app installed and signed in (`adb devices`).
 *   node e2e/search-keyboard.mjs [word]          (default: "biscuit")
 */
import { adb, keyboardShown, PACKAGE, screen, sleep, tap, until } from "./device.mjs";

const WORD = process.argv[2] ?? "biscuit";
const PAUSE_MS = 700; // longer than the search's 250 ms pause, so results render between letters

/** The search box: the screen's first focusable EditText with a hint (by class and attributes,
 * so the app's language doesn't matter; the box's container also reports as an EditText). */
function searchBox() {
  const nodes = screen();
  const node = nodes.find((n) => n.cls === "android.widget.EditText" && n.focusable && n.hint);
  if (!node) return null;
  return { ...node, results: nodes.filter((n) => n.text.startsWith("₹")).length };
}

const failures = [];
function check(ok, what) {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failures.push(what);
}

// From a fresh start: home, then a tap on the search box, as a shop would do it.
adb("shell", "am", "force-stop", PACKAGE);
adb("shell", "am", "start", "-W", "-n", `${PACKAGE}/.MainActivity`);
const entry = await (async () => {
  for (let i = 0; i < 20; i++) {
    const nodes = screen();
    // The home screen's search entry: reported as a clickable EditText without a hint (the
    // search screen's real input has one).
    const node = nodes.find((n) => n.cls === "android.widget.EditText" && n.clickable && !n.hint);
    if (node && nodes.some((n) => n.text.includes("₹"))) return node;
    await sleep(700);
  }
  return null;
})();
check(entry !== null, "home shows the search box");
if (entry) tap(entry);
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
const results = box?.results ?? 0;
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
