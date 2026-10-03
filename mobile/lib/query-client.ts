import { QueryClient } from "@tanstack/react-query";

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
