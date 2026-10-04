import { describe, expect, it } from "vitest";

import { assetLinks } from "./app-links";

const PRINT = Array.from({ length: 32 }, (_, i) =>
  i.toString(16).padStart(2, "0").toUpperCase(),
).join(":");

describe("assetLinks", () => {
  it("states the app and its certificates", () => {
    expect(assetLinks("in.example.shop", `${PRINT.toLowerCase()}, ${PRINT}`)).toEqual([
      {
        relation: ["delegate_permission/common.handle_all_urls"],
        target: {
          namespace: "android_app",
          package_name: "in.example.shop",
          sha256_cert_fingerprints: [PRINT, PRINT],
        },
      },
    ]);
  });

  it("states nothing until the deployment is configured", () => {
    expect(assetLinks(undefined, PRINT)).toBeNull();
    expect(assetLinks("in.example.shop", "")).toBeNull();
    expect(assetLinks("in.example.shop", "not-a-fingerprint")).toBeNull();
    expect(assetLinks("not an id", PRINT)).toBeNull();
  });
});
