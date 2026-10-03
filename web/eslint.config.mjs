import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Words on screen go through i18n keys (ADR-060): text between tags, string children and the
// attributes people see or hear. Punctuation and symbols ("·", "—", "₹") are fine.
const WORDS = "/[A-Za-z]{2,}/";
const I18N = 'Words on screen go through i18n: t("key") with the text in messages/en.json.';

// Numbers inside messages go through the shared formatter (ADR-060 item 4): translations come from
// lib/i18n, which formats every number they are given (6,029; 1,23,456), and numbers are
// formatted only by lib/format.ts.
const NUMBERS =
  "Use lib/i18n/translations (or lib/i18n/server): it formats numbers in messages with Indian grouping.";
const FORMAT = "Format numbers with lib/format.ts (Indian grouping, digits 0–9 in every language).";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
    ignores: ["**/*.test.{ts,tsx}", "lib/i18n/**", "lib/format.ts", "lib/api/generated/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "next-intl",
              importNames: ["useTranslations", "useFormatter"],
              message: NUMBERS,
            },
            { name: "next-intl/server", importNames: ["getTranslations"], message: NUMBERS },
          ],
        },
      ],
      "no-restricted-properties": [
        "error",
        { object: "Number", property: "toLocaleString", message: FORMAT },
        { object: "Intl", property: "NumberFormat", message: FORMAT },
      ],
    },
  },
  {
    files: ["app/**/*.tsx", "components/**/*.tsx"],
    ignores: ["**/*.test.tsx", "app/design-system/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: `JSXText[value=${WORDS}]`, message: I18N },
        {
          selector: `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > Literal[value=${WORDS}]`,
          message: I18N,
        },
        {
          selector: `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
          message: I18N,
        },
        {
          selector: `JSXAttribute[name.name=/^(aria-label|aria-description|title|placeholder|alt|label)$/] > Literal[value=${WORDS}]`,
          message: I18N,
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "lib/api/generated/**",
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
