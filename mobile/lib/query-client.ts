import { focusManager, QueryClient } from "@tanstack/react-query";
import { AppState } from "react-native";

import { ApiError } from "@/lib/shared/errors";

/** Like the web's: no retry for a refusal (4xx), a couple for the network or the server. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) => !(error instanceof ApiError && error.isClientError) && count < 2,
      },
      mutations: { retry: false },
    },
  });
}

/** Back in the foreground (from a payment tab, WhatsApp or the home screen), screens refresh what
 * they show, as a browser tab does when it gets the focus again. Returns the unsubscribe. */
export function followAppState(): () => void {
  const subscription = AppState.addEventListener("change", (state) =>
    focusManager.setFocused(state === "active"),
  );
  return () => subscription.remove();
}
