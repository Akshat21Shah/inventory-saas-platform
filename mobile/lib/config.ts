import Constants from "expo-constants";

/** Build-time settings from app.config.ts (`extra`). */
interface Extra {
  apiUrl: string;
  platformDomain: string;
  release: boolean;
  sentryDsn: string;
  build: number;
}

const extra = (Constants.expoConfig?.extra ?? {}) as Partial<Extra>;

export const config: Extra = {
  apiUrl: (extra.apiUrl ?? "http://10.0.2.2:3000").replace(/\/$/, ""),
  platformDomain: extra.platformDomain ?? "localhost",
  release: extra.release ?? false,
  sentryDsn: extra.sentryDsn ?? "",
  build: extra.build ?? 0,
};

/** The version every API request carries (`X-App-Version`, ADR-061 item 6). */
export const APP_VERSION: string = Constants.expoConfig?.version ?? "0.0.0";

/** The app's name and application ID, from `app-identity.js` through the build. */
export const APP_NAME: string = Constants.expoConfig?.name ?? "Shop";
export const APPLICATION_ID: string = Constants.expoConfig?.android?.package ?? "";
