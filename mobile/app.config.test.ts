/** Plain http only in development builds (owner, checkpoint review). */
import type { ConfigContext, ExpoConfig } from "expo/config";

function build(env: Record<string, string>): ExpoConfig {
  const saved = { ...process.env };
  Object.assign(process.env, env);
  try {
    let made: ExpoConfig | undefined;
    jest.isolateModules(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports -- fresh per environment
      const make = require("./app.config").default as (context: ConfigContext) => ExpoConfig;
      made = make({ config: {} } as ConfigContext);
    });
    return made as ExpoConfig;
  } finally {
    process.env = saved;
  }
}

describe("the build configuration", () => {
  it("refuses a release build with a non-https address", () => {
    for (const url of ["http://shop.example.in", "shop.example.in", "ftp://shop.example.in", ""]) {
      expect(() => build({ APP_RELEASE: "1", APP_API_URL: url })).toThrow(/https/);
    }
  });

  it("makes a release build https-only, its links verified", () => {
    const config = build({
      APP_RELEASE: "1",
      APP_API_URL: "https://shop.example.in",
      APP_PLATFORM_DOMAIN: "shop.example.in",
    });
    const props = config.plugins?.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === "expo-build-properties",
    );
    expect(
      (props as [string, { android: { usesCleartextTraffic: boolean } }])[1].android
        .usesCleartextTraffic,
    ).toBe(false);
    const filter = config.android?.intentFilters?.[0];
    expect(filter?.autoVerify).toBe(true);
    expect(filter?.data).toEqual([
      { scheme: "https", host: "*.shop.example.in", pathPrefix: "/shop" },
    ]);
    expect(config.android?.blockedPermissions).toContain("android.permission.SYSTEM_ALERT_WINDOW");
  });

  it("lets development builds use the LAN stack over http", () => {
    const config = build({ APP_RELEASE: "0", APP_API_URL: "http://192-168-0-106.nip.io:3000" });
    expect(config.extra?.apiUrl).toBe("http://192-168-0-106.nip.io:3000");
  });
});
