/**
 * The Android shop app's build configuration (ADR-061). The native project is generated from this
 * file (`expo prebuild`); nothing native is committed.
 *
 * Build-time settings (environment):
 * - `APP_API_URL`: where the app reaches the API, the platform's generic web address. Default: the
 *   dev stack on the emulator's view of this Mac (`http://10.0.2.2:3000`). For a phone in LAN mode,
 *   `http://<lan-ip-with-dashes>.nip.io:3000`.
 * - `APP_PLATFORM_DOMAIN`: the domain whose distributor subdomains' /shop links open the app.
 * - `APP_RELEASE=1`: a release build (https only, App Links verified). Development builds allow
 *   plain http (the LAN stack) and declare the links without verification.
 * - `APP_SENTRY_DSN`: crash reports (none when empty).
 */
import type { ConfigContext, ExpoConfig } from "expo/config";

import version from "./version.json";

// eslint-disable-next-line @typescript-eslint/no-require-imports -- plain JS, read by Node here
const { APPLICATION_ID, APP_NAME, URL_SCHEME } = require("./app-identity") as {
  APPLICATION_ID: string;
  APP_NAME: string;
  URL_SCHEME: string;
};

const release = process.env.APP_RELEASE === "1";
const apiUrl = process.env.APP_API_URL ?? "http://10.0.2.2:3000";
const platformDomain = process.env.APP_PLATFORM_DOMAIN ?? "localhost";

// Plain http only in development builds (owner, checkpoint review): a release build refuses any
// other address, so the build stops here (tests: app.config.test.ts; CI: mobile-build).
if (release && !/^https:\/\/[^/\s]+/.test(apiUrl)) {
  throw new Error(`A release build needs an https APP_API_URL, not ${JSON.stringify(apiUrl)}.`);
}

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: APP_NAME,
  slug: "shop",
  version: version.version,
  orientation: "portrait",
  icon: "./assets/icon.png",
  scheme: URL_SCHEME,
  userInterfaceStyle: "light",
  android: {
    package: APPLICATION_ID,
    versionCode: version.build,
    adaptiveIcon: { foregroundImage: "./assets/adaptive-icon.png", backgroundColor: "#2f5bea" },
    allowBackup: false, // the session's refresh token never leaves the phone
    // Only what the shop app uses (Data safety, pre-production item 47). The overlay permission
    // is the development menu's.
    blockedPermissions: [
      "android.permission.READ_EXTERNAL_STORAGE",
      "android.permission.WRITE_EXTERNAL_STORAGE",
      ...(release ? ["android.permission.SYSTEM_ALERT_WINDOW"] : []),
    ],
    predictiveBackGestureEnabled: false,
    intentFilters: [
      {
        action: "VIEW",
        autoVerify: release,
        category: ["BROWSABLE", "DEFAULT"],
        data: [
          { scheme: release ? "https" : "http", host: `*.${platformDomain}`, pathPrefix: "/shop" },
        ],
      },
    ],
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    "expo-image",
    "expo-localization",
    // Hindi and Marathi at medium weight, as the web (checkpoint review item 6, ADR-061).
    ["expo-font", { fonts: ["./assets/fonts/NotoSansDevanagari-Medium.ttf"] }],
    "@sentry/react-native",
    [
      "expo-build-properties",
      {
        android: {
          usesCleartextTraffic: !release,
          enableMinifyInReleaseBuilds: true,
          enableShrinkResourcesInReleaseBuilds: true,
        },
      },
    ],
  ],
  extra: {
    apiUrl,
    platformDomain,
    release,
    sentryDsn: process.env.APP_SENTRY_DSN ?? "",
    build: version.build,
  },
});
