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

/** Property names whose value is parsed as HTML. */
const HTML_PROPS = "/^(innerHTML|outerHTML|srcdoc|srcDoc)$/";
/** Methods that parse a string as HTML. Banned on any access, not only calls (covers `.call`). */
const HTML_METHODS =
  "/^(insertAdjacentHTML|createContextualFragment|setHTMLUnsafe|parseHTMLUnsafe)$/";
/** Attribute names that take HTML or script: `srcdoc` and event handlers (`on*`). */
const HTML_ATTRS = "/^(srcdoc|on[a-z]+)$/i";
const WRITE = "/^(write|writeln)$/";

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
    selector: `AssignmentExpression > MemberExpression.left[property.name=${HTML_PROPS}], AssignmentExpression > MemberExpression.left[property.value=${HTML_PROPS}]`,
    message: `${T1} assignment to innerHTML, outerHTML or srcdoc. ${PLAIN_TEXT}`,
  },
  {
    // Object literals with these keys reach the DOM through Object.assign,
    // spread props or createElement("iframe", { srcDoc }).
    selector: `Property[key.name=${HTML_PROPS}], Property[key.value=${HTML_PROPS}]`,
    message: `${T1} an object property innerHTML, outerHTML, srcdoc or srcDoc (Object.assign, props). ${PLAIN_TEXT}`,
  },
  {
    selector: `MemberExpression[property.name=${HTML_METHODS}], MemberExpression[property.value=${HTML_METHODS}]`,
    message: `${T1} insertAdjacentHTML, createContextualFragment, setHTMLUnsafe and parseHTMLUnsafe parse HTML. ${PLAIN_TEXT}`,
  },
  {
    selector: `CallExpression[callee.property.name='setAttribute'][arguments.0.value=${HTML_ATTRS}]:not([arguments.0.value=/^open$/i]), CallExpression[callee.property.name='setAttributeNS'][arguments.1.value=${HTML_ATTRS}]:not([arguments.1.value=/^open$/i])`,
    message: `${T1} setAttribute with srcdoc or an on* event handler. ${PLAIN_TEXT}`,
  },
  {
    // document.write, document["write"], window.document.write, globalThis.document.writeln.
    selector: [
      `MemberExpression[property.name=${WRITE}][object.name='document']`,
      `MemberExpression[property.value=${WRITE}][object.name='document']`,
      `MemberExpression[property.name=${WRITE}][object.property.name='document']`,
      `MemberExpression[property.value=${WRITE}][object.property.name='document']`,
      `MemberExpression[property.name=${WRITE}][object.property.value='document']`,
      `MemberExpression[property.value=${WRITE}][object.property.value='document']`,
    ].join(", "),
    message: `${T1} document.write and document.writeln. ${PLAIN_TEXT}`,
  },
  {
    // new DOMParser(), new window.DOMParser(), new globalThis["DOMParser"]().
    selector:
      "NewExpression[callee.name='DOMParser'], NewExpression[callee.property.name='DOMParser'], NewExpression[callee.property.value='DOMParser']",
    message: `${T1} DOMParser parses HTML. ${PLAIN_TEXT}`,
  },
  {
    selector: "JSXAttribute[name.name=/^srcdoc$/i]",
    message: `${T1} iframe srcDoc renders raw HTML. ${PLAIN_TEXT}`,
  },
];

const ALL_SOURCES = "**/*.{js,mjs,cjs,jsx,ts,mts,cts,tsx}";
const JS_SOURCES = "**/*.{js,mjs,cjs,jsx}";

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
          // Virtual files used by the lint tests in `src/security/` to prove
          // that the rules below fire. They never exist on disk. They are
          // type-checked with the app compiler options (JSX, DOM, React).
          allowDefaultProject: ["src/__lint_fixture__.{ts,tsx,mts,cts}"],
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
    // Plain JavaScript files are not part of any TypeScript project:
    // lint them without type information. The HTML-sink ban still applies.
    files: [JS_SOURCES],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: false,
        ecmaFeatures: { jsx: true },
      },
    },
  },
  {
    files: [ALL_SOURCES],
    ...reactHooks.configs.flat["recommended-latest"],
  },
  {
    files: [ALL_SOURCES],
    rules: {
      "no-restricted-syntax": ["error", ...htmlSinkBans],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      eqeqeq: ["error", "always"],
    },
  },
  {
    // Type-aware variants for TypeScript files.
    files: ["**/*.{ts,mts,cts,tsx}"],
    rules: {
      "no-implied-eval": "off",
      "@typescript-eslint/no-implied-eval": "error",
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
