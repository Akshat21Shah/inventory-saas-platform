import { Redirect } from "expo-router";

/** The web's sign-in address (in SMS and WhatsApp messages) opened in the app: signed in, home;
 * signed out, the shop layout sends the shop to the app's sign-in. */
export default function ShopLogin() {
  return <Redirect href="/shop" />;
}
