import "@/lib/polyfills";

import * as Sentry from "@sentry/react-native";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState, type ReactNode } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { UpdateGate } from "@/components/app/update-gate";
import { AuthProvider, useAuth } from "@/lib/auth/auth-provider";
import { APP_VERSION, config } from "@/lib/config";
import { loadLanguage } from "@/lib/i18n/language";
import { I18nProvider } from "@/lib/i18n/provider";
import { followConnection } from "@/lib/offline/online";
import { persistOptions } from "@/lib/offline/persist";
import { followAppState, makeQueryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/theme/theme";

// Crash and error reports (ADR-061 item 13): only with a DSN; no phone numbers or tokens.
if (config.sentryDsn) {
  Sentry.init({
    dsn: config.sentryDsn,
    release: `shop@${APP_VERSION}+${config.build}`,
    sendDefaultPii: false,
    beforeBreadcrumb: (crumb) =>
      crumb.category === "fetch" || crumb.category === "xhr" ? null : crumb,
  });
}

followConnection(); // requests wait while the phone is offline (ADR-061 item 10)

/** The distributor's colours once signed in, the platform's before. */
function Branded({ children }: { children: ReactNode }) {
  const { branding } = useAuth();
  return <ThemeProvider brand={branding?.primary_color ?? null}>{children}</ThemeProvider>;
}

function RootLayout() {
  const [queryClient] = useState(makeQueryClient);
  useEffect(() => {
    void loadLanguage(); // the saved language replaces the phone's as soon as it is read
    return followAppState();
  }, []);
  return (
    <SafeAreaProvider>
      <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
        <I18nProvider>
          <AuthProvider>
            <Branded>
              <StatusBar style="dark" />
              <UpdateGate>
                <Stack screenOptions={{ headerShown: false }} />
              </UpdateGate>
            </Branded>
          </AuthProvider>
        </I18nProvider>
      </PersistQueryClientProvider>
    </SafeAreaProvider>
  );
}

export default config.sentryDsn ? Sentry.wrap(RootLayout) : RootLayout;
