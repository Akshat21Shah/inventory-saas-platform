// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["android/*", "ios/*", "lib/api/generated/*", "lib/shared/*", "coverage/*"],
  },
  {
    // Numbers in messages go through the shared formatter (ADR-060), as on the web.
    files: ["**/*.ts", "**/*.tsx"],
    ignores: ["lib/i18n/**", "**/*.test.ts", "**/*.test.tsx", "tests/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "use-intl",
              importNames: ["useTranslations"],
              message: "Use useTranslations from @/lib/i18n/translations (numbers grouped).",
            },
          ],
        },
      ],
      "no-restricted-properties": [
        "error",
        { object: "Intl", property: "NumberFormat", message: "Use @/lib/shared/format." },
        { property: "toLocaleString", message: "Use @/lib/shared/format." },
      ],
    },
  },
]);
