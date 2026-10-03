/** Render a screen with what the app gives every screen: queries, texts in a language, theme. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react-native";
import type { ReactElement } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { IntlProvider } from "use-intl";

import { messagesFor } from "@/lib/i18n/messages";
import { intlLocale } from "@/lib/shared/i18n-config";
import { ThemeProvider } from "@/lib/theme/theme";

const METRICS = {
  frame: { x: 0, y: 0, width: 360, height: 640 },
  insets: { top: 0, left: 0, right: 0, bottom: 0 },
};

export function renderScreen(ui: ReactElement, { language = "en" }: { language?: string } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <SafeAreaProvider initialMetrics={METRICS}>
      <QueryClientProvider client={client}>
        <IntlProvider
          locale={intlLocale(language)}
          messages={messagesFor(language)}
          timeZone="Asia/Kolkata"
        >
          <ThemeProvider brand={null}>{ui}</ThemeProvider>
        </IntlProvider>
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}
