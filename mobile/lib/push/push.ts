/**
 * Push notifications on the phone (ADR-061 item 7; owner, checkpoint review item 4).
 *
 * - Three Android channels, so a shop can silence one kind in the phone's settings and keep the
 *   others: Orders and deliveries, Bills and payments, Offers and announcements. The server puts
 *   each message on its kind's channel. With the app closed or in the background Android plays the
 *   phone's notification sound and vibrates, and follows silent and Do Not Disturb.
 * - With the app open, a message plays a short sound (the same system sound, so silent and Do Not
 *   Disturb still apply) unless the shop switched that off in Account.
 * - The phone's FCM token is registered with the server after sign-in and removed at sign-out.
 *   Builds without Firebase (`google-services.json`) skip all of this.
 */
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";

import { shopDeviceRegister, shopDeviceRemove } from "@/lib/api/generated/endpoints/shop/shop";
import { APP_VERSION, config } from "@/lib/config";

export const CHANNELS = ["orders", "money", "offers"] as const;
export type Channel = (typeof CHANNELS)[number];

const SOUND_KEY = "app.notificationSound";
const TOKEN_KEY = "app.pushToken";

// --- The in-app sound switch --------------------------------------------------------------------

let soundOn = true;
const soundListeners = new Set<(on: boolean) => void>();

export async function loadSoundSetting(): Promise<boolean> {
  soundOn = (await SecureStore.getItemAsync(SOUND_KEY)) !== "off";
  soundListeners.forEach((listener) => listener(soundOn));
  return soundOn;
}

export function soundSetting(): boolean {
  return soundOn;
}

export async function setSoundSetting(on: boolean): Promise<void> {
  soundOn = on;
  await SecureStore.setItemAsync(SOUND_KEY, on ? "on" : "off");
  soundListeners.forEach((listener) => listener(on));
}

export function onSoundSettingChange(listener: (on: boolean) => void): () => void {
  soundListeners.add(listener);
  return () => void soundListeners.delete(listener);
}

/** What a message does while the app is open: in the list always; the banner and its sound only
 * with the switch on. */
export function foregroundBehaviour(): Notifications.NotificationBehavior {
  return {
    shouldShowBanner: soundOn,
    shouldShowList: true,
    shouldPlaySound: soundOn,
    shouldSetBadge: false,
  };
}

// --- Channels -----------------------------------------------------------------------------------

/** Creates (or renames, after a language change) the app's channels. Sound and vibration are the
 * phone's defaults; offers don't pop up over what the shop is doing. */
export async function setUpChannels(names: Record<Channel, string>): Promise<void> {
  for (const id of CHANNELS) {
    await Notifications.setNotificationChannelAsync(id, {
      name: names[id],
      importance:
        id === "offers"
          ? Notifications.AndroidImportance.DEFAULT
          : Notifications.AndroidImportance.HIGH,
      sound: "default",
      enableVibrate: true,
      vibrationPattern: [0, 250, 200, 250],
    });
  }
}

// --- This phone with the server -----------------------------------------------------------------

/** After sign-in: ask once for permission (Android 13 and up), then tell the server this phone's
 * token. Nothing happens in a build without Firebase or when the shop says no. */
export async function registerThisPhone(): Promise<void> {
  if (!config.push) return;
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== "granted") ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== "granted") return;
  const token = String((await Notifications.getDevicePushTokenAsync()).data);
  await shopDeviceRegister({ token, platform: "ANDROID", app_version: APP_VERSION });
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

/** A new token from Firebase (rare: app data cleared, restored phone): register it. */
export function followTokenChanges(): () => void {
  if (!config.push) return () => undefined;
  const subscription = Notifications.addPushTokenListener(({ data }) => {
    const token = String(data);
    void shopDeviceRegister({ token, platform: "ANDROID", app_version: APP_VERSION })
      .then(() => SecureStore.setItemAsync(TOKEN_KEY, token))
      .catch(() => undefined);
  });
  return () => subscription.remove();
}

/** Before signing out: this phone stops getting the shop's messages. */
export async function forgetThisPhone(): Promise<void> {
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  if (!token) return;
  await shopDeviceRemove({ token }).catch(() => undefined); // offline: the server forgets it later
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
