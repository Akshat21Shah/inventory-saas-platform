import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Words on screen go through i18n keys (ADR-060): text between tags, string children and the
// attributes people see or hear. Punctuation and symbols ("·", "—", "₹") are fine.
const WORDS = "/[A-Za-z]{2,}/";
const I18N = 'Words on screen go through i18n: t("key") with the text in messages/en.json.';

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
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
