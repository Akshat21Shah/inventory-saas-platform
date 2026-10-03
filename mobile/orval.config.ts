import { defineConfig } from "orval";

// The app's API client, generated from the same schema as the web's (ADR-061 item 3): only the
// shop's, sign-in and public endpoints, which is everything the shop app may call. Never edit
// lib/api/generated; `make api-client` regenerates the web's and this one.
export default defineConfig({
  shop: {
    input: { target: "../backend/openapi.yaml", filters: { tags: ["auth", "shop", "public"] } },
    output: {
      mode: "tags-split",
      target: "lib/api/generated/endpoints",
      schemas: "lib/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: { path: "lib/api/fetcher.ts", name: "apiFetch" },
        query: { signal: true },
      },
    },
  },
});
