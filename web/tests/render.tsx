import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { IntlErrorCode, NextIntlClientProvider, type IntlError } from "next-intl";
import { useState, type ReactElement, type ReactNode } from "react";

import { intlLocale } from "@/lib/i18n/config";
import messages from "@/messages/en.json";
import hindi from "@/messages/hi.json";
import marathi from "@/messages/mr.json";

type Messages = { [key: string]: string | Messages };

/** A language's messages over the English ones, as the app loads them. */
function over(base: Messages, own: Messages): Messages {
  const out: Messages = { ...base };
  for (const [key, value] of Object.entries(own)) {
    const under = base[key];
    out[key] = typeof value === "object" && typeof under === "object" ? over(under, value) : value;
  }
  return out;
}

const CATALOGS: Record<string, Messages> = {
  en: messages,
  hi: over(messages, hindi),
  mr: over(messages, marathi),
};

/** A missing or broken message fails the test instead of silently rendering the key. */
function failOnIntlError(error: IntlError) {
  throw new Error(
    `${IntlErrorCode[error.code as keyof typeof IntlErrorCode] ?? error.code}: ${error.message}`,
  );
}

function Providers({ children, locale = "en" }: { children: ReactNode; locale?: string }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider
        locale={intlLocale(locale)}
        messages={CATALOGS[locale] ?? messages}
        timeZone="Asia/Kolkata"
        onError={failOnIntlError}
      >
        {children}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

/** Render with the English catalogue (or ``locale``'s) and a fresh query client; ``rerender``
 * keeps the providers. */
export function renderWithIntl(
  ui: ReactElement,
  { locale = "en", ...options }: Omit<RenderOptions, "wrapper"> & { locale?: string } = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <Providers locale={locale}>{children}</Providers>;
  }
  return render(ui, { wrapper: Wrapper, ...options });
}
