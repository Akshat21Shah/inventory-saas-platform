import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { IntlErrorCode, NextIntlClientProvider, type IntlError } from "next-intl";
import { useState, type ReactElement, type ReactNode } from "react";

import messages from "@/messages/en.json";

/** A missing or broken message fails the test instead of silently rendering the key. */
function failOnIntlError(error: IntlError) {
  throw new Error(
    `${IntlErrorCode[error.code as keyof typeof IntlErrorCode] ?? error.code}: ${error.message}`,
  );
}

function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider
        locale="en"
        messages={messages}
        timeZone="Asia/Kolkata"
        onError={failOnIntlError}
      >
        {children}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

/** Render with the English catalogue and a fresh query client; `rerender` keeps the providers. */
export function renderWithIntl(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: Providers, ...options });
}
