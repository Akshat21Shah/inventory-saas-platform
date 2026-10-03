#!/usr/bin/env bash
# CI's emulator job (ADR-061, 11b.10), on the booted emulator with the stack and the seed running,
# one job per language (LANGUAGES=en, hi or mr): installs the app and signs in; the English job
# runs the flows, then each job tours every screen in its language. three-taps comes before
# notifications: the order it places gives the shop an unread message. pay-online needs Chrome on
# the emulator and stays a local check (and the owner's real-phone check).
set -euo pipefail
cd "$(dirname "$0")/.."

adb install -r android/app/build/outputs/apk/release/app-release.apk
node e2e/sign-in.mjs
if [[ "${LANGUAGES:-en}" == "en" ]]; then
  node e2e/three-taps.mjs
  node e2e/search-keyboard.mjs
  node e2e/notifications.mjs
  node e2e/offline.mjs
fi
node e2e/tour.mjs
