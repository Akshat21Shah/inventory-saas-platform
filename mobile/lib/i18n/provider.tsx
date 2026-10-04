import { useEffect, useMemo, useState, type ReactNode } from "react";
import { IntlProvider } from "use-intl";

import { TIME_ZONE, intlLocale, type Locale } from "@/lib/shared/i18n-config";

import { currentLanguage, onLanguageChange } from "./language";
import { messagesFor } from "./messages";

/** The texts in the app's current language; switching language re-renders every screen. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [code, setCode] = useState<Locale>(currentLanguage());
  useEffect(() => onLanguageChange(setCode), []);
  const messages = useMemo(() => messagesFor(code), [code]);
  return (
    <IntlProvider
      locale={intlLocale(code)}
      timeZone={TIME_ZONE}
      messages={messages}
      onError={(error) => {
        if (__DEV__) console.warn(error.message);
      }}
      getMessageFallback={({ namespace, key }) => [namespace, key].filter(Boolean).join(".")}
    >
      {children}
    </IntlProvider>
  );
}
