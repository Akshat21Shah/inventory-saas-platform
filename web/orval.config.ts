import { defineConfig } from "orval";

// Generated client: never edit files under lib/api/generated (CLAUDE.md §6). Regenerate with
// `make api-client`, which exports backend/openapi.yaml first.
export default defineConfig({
  platform: {
    input: { target: "../backend/openapi.yaml" },
    output: {
      mode: "tags-split",
      target: "lib/api/generated/endpoints",
      schemas: "lib/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: { path: "lib/api/fetcher.ts", name: "apiFetch" },
        // Defaults: useQuery for GET, useMutation for writes.
        query: { signal: true },
      },
    },
  },
});
