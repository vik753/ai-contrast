// @ts-check
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Threat model T1, browser control 5: React escaping only.
 * Raw HTML injection is forbidden everywhere, with no exceptions.
 */
const forbidRawHtml = {
  selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
  message:
    "dangerouslySetInnerHTML is forbidden (threat model T1). Render untrusted text as plain text.",
};

export default defineConfig(
  {
    ignores: ["dist/", "coverage/", "node_modules/"],
  },
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: {
          // Virtual file used by `src/security/lint-rules.test.ts` to prove that
          // the rules below fire. It never exists on disk.
          allowDefaultProject: ["src/__lint_fixture__.tsx"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
    ...reactHooks.configs.flat["recommended-latest"],
  },
  {
    files: ["**/*.{js,ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", forbidRawHtml],
      "no-eval": "error",
      "no-implied-eval": "off",
      "@typescript-eslint/no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      eqeqeq: ["error", "always"],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
    },
  },
  {
    // Testing Library idiom: `waitFor(() => expect(...))`.
    files: ["src/**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-confusing-void-expression": "off",
    },
  },
);
