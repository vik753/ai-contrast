// @ts-check
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Threat model T1, browser control 5: React escaping only.
 * Every API that turns a string into HTML or script is forbidden, with no
 * exceptions. Inline `eslint-disable` comments are ignored
 * (`noInlineConfig`), so the ban cannot be switched off in a source file.
 */
const T1 = "Forbidden by threat model T1 (XSS):";
const PLAIN_TEXT = "Render untrusted text as plain text (React text nodes or textContent).";

const htmlSinkBans = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: `${T1} dangerouslySetInnerHTML. ${PLAIN_TEXT}`,
  },
  {
    selector:
      "Property[key.name='dangerouslySetInnerHTML'], Property[key.value='dangerouslySetInnerHTML']",
    message: `${T1} a dangerouslySetInnerHTML prop object (spread props). ${PLAIN_TEXT}`,
  },
  {
    selector:
      "MemberExpression[property.name='dangerouslySetInnerHTML'], MemberExpression[property.value='dangerouslySetInnerHTML']",
    message: `${T1} access to dangerouslySetInnerHTML. ${PLAIN_TEXT}`,
  },
  {
    // Inside a JSX dangerouslySetInnerHTML attribute the attribute itself is
    // already reported; report one error per sink.
    selector:
      ":matches(Property[key.name='__html'], Property[key.value='__html'], MemberExpression[property.name='__html']):not(JSXAttribute[name.name='dangerouslySetInnerHTML'] *)",
    message: `${T1} an __html object (raw HTML for React). ${PLAIN_TEXT}`,
  },
  {
    selector:
      "AssignmentExpression > MemberExpression.left[property.name=/^(innerHTML|outerHTML)$/], AssignmentExpression > MemberExpression.left[property.value=/^(innerHTML|outerHTML)$/]",
    message: `${T1} assignment to innerHTML or outerHTML. ${PLAIN_TEXT}`,
  },
  {
    selector:
      "CallExpression > MemberExpression.callee[property.name=/^(insertAdjacentHTML|createContextualFragment|setHTMLUnsafe|parseHTMLUnsafe)$/]",
    message: `${T1} insertAdjacentHTML, createContextualFragment, setHTMLUnsafe and parseHTMLUnsafe parse HTML. ${PLAIN_TEXT}`,
  },
  {
    selector: "MemberExpression[object.name='document'][property.name=/^(write|writeln)$/]",
    message: `${T1} document.write and document.writeln. ${PLAIN_TEXT}`,
  },
  {
    selector: "NewExpression[callee.name='DOMParser']",
    message: `${T1} DOMParser parses HTML. ${PLAIN_TEXT}`,
  },
  {
    selector: "JSXAttribute[name.name=/^srcdoc$/i]",
    message: `${T1} iframe srcDoc renders raw HTML. ${PLAIN_TEXT}`,
  },
];

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
          // Virtual file used by the lint tests in `src/security/` to prove
          // that the rules below fire. It never exists on disk. It is
          // type-checked with the app compiler options (JSX, DOM, React).
          allowDefaultProject: ["src/__lint_fixture__.tsx"],
          defaultProject: "tsconfig.app.json",
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: {
      // `eslint-disable` comments have no effect: security rules cannot be
      // switched off in a source file.
      noInlineConfig: true,
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
    ...reactHooks.configs.flat["recommended-latest"],
  },
  {
    files: ["**/*.{js,ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", ...htmlSinkBans],
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
