/**
 * THE APP'S IDENTITY — one clearly marked setting (ADR-061 items 5 and 14).
 *
 * Development placeholders. Google Play refuses `com.example` application IDs, so a build with
 * this ID can't be uploaded by mistake. The final ID and name are chosen before the FIRST Play
 * Store upload: the application ID can never change afterwards (pre-production item 45).
 *
 * Read by app.config.ts only; screens get the name and ID from the built app (`lib/config.ts`).
 */
// TODO(verify): the final application ID and name (pre-production item 45).
module.exports = {
  APPLICATION_ID: "com.example.shop",
  APP_NAME: "Shop",
  /** Links from the app's own screens and, in development, links that open the app. */
  URL_SCHEME: "shopapp",
};
