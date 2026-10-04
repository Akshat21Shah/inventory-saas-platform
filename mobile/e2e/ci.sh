#!/usr/bin/env bash
# CI's emulator job (ADR-061, 11b.10), on the booted emulator with the stack and the seed running,
# one job per language (LANGUAGES=en, hi or mr): installs the app and signs in; the English job
# runs the flows, then each job tours every screen in its language. three-taps comes before
# notifications: the order it places gives the shop an unread message. pay-online needs Chrome on
# the emulator and stays a local check (and the owner's real-phone check).
set -euo pipefail
cd "$(dirname "$0")/.."

# On a failure: what the phone showed, its elements and the app's log, kept with the screenshots.
on_failure() {
  mkdir -p e2e/screenshots/failure
  adb exec-out screencap -p > e2e/screenshots/failure/screen.png || true
  adb shell uiautomator dump /sdcard/failure.xml && adb exec-out cat /sdcard/failure.xml \
    > e2e/screenshots/failure/screen.xml || true
  adb logcat -d -t 2000 > e2e/screenshots/failure/logcat.txt || true
}
trap on_failure ERR

adb install -r android/app/build/outputs/apk/release/app-release.apk
node e2e/sign-in.mjs
if [[ "${LANGUAGES:-en}" == "en" ]]; then
  node e2e/three-taps.mjs
  node e2e/search-keyboard.mjs
  node e2e/notifications.mjs
  node e2e/offline.mjs
fi
node e2e/tour.mjs
