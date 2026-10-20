// @vitest-environment node
/**
 * PR #3 review follow-ups / threat model T1 — lint config gaps:
 * implied eval in JS files, type-aware linting of `eslint.config.js`,
 * no false positives on destructuring reads, `contentDocument.write`, and
 * template-literal property names.
 *
 * Each sink fixture marks its sink line with a trailing `// sink` comment.
 */
import { fileURLToPath } from "node:url";
import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND_DIR = fileURLToPath(new URL("../../", import.meta.url));
const JS_PATH = "src/__lint_fixture__.js";
const TSX_PATH = "src/__lint_fixture__.tsx";
const RULE = "no-restricted-syntax";
const EVAL_RULES = new Set(["no-eval", "no-implied-eval", "@typescript-eslint/no-implied-eval"]);
const LINT_TIMEOUT_MS = 60_000;

let eslintInstance: ESLint | undefined;

function eslint(): ESLint {
  eslintInstance ??= new ESLint({ cwd: FRONTEND_DIR });
  return eslintInstance;
}

async function lint(code: string, filePath: string): Promise<Linter.LintMessage[]> {
  const results = await eslint().lintText(code, { filePath });
  expect(results).toHaveLength(1);
  const [result] = results;
  if (!result) {
    throw new Error("ESLint returned no result");
  }
  return result.messages;
}

function sinkLine(code: string): number {
  const index = code.split("\n").findIndex((line) => line.trimEnd().endsWith("// sink"));
  if (index < 0) {
    throw new Error("Fixture has no `// sink` marker");
  }
  return index + 1;
}

function errorLines(messages: Linter.LintMessage[], rules: ReadonlySet<string>): number[] {
  return messages
    .filter((m) => m.ruleId !== null && rules.has(m.ruleId) && m.severity === 2)
    .map((m) => m.line);
}

function fatalOrIgnored(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.fatal === true || m.ruleId === null);
}

const RESTRICTED = new Set([RULE]);

describe("implied eval in JS files (PR #3 follow-up 1)", () => {
  it.each([
    [
      "set_timeout_string",
      `export function f() {
  setTimeout("alert(1)"); // sink
}
`,
    ],
    [
      "window_set_timeout_string",
      `export function f() {
  window.setTimeout("alert(1)"); // sink
}
`,
    ],
    [
      "window_eval",
      `export function f() {
  return window.eval("1"); // sink
}
`,
    ],
  ] as const)(
    "test_lint_js_%s_reports_eval_rule_error",
    async (_name, code) => {
      const messages = await lint(code, JS_PATH);
      expect(fatalOrIgnored(messages)).toEqual([]);
      expect(errorLines(messages, EVAL_RULES)).toContain(sinkLine(code));
    },
    LINT_TIMEOUT_MS,
  );
});

type RuleEntry = Linter.RuleEntry | undefined;

function severity(entry: RuleEntry): number {
  const level: unknown = Array.isArray(entry) ? entry[0] : entry;
  if (level === "error" || level === 2) return 2;
  if (level === "warn" || level === 1) return 1;
  return 0;
}

describe("eslint.config.js is linted with type information (PR #3 follow-up 2)", () => {
  it(
    "test_eslint_config_js_has_no_floating_promises_as_error",
    async () => {
      const config = (await eslint().calculateConfigForFile("eslint.config.js")) as
        Linter.Config | undefined;
      expect(config).toBeDefined();
      expect(severity(config?.rules?.["@typescript-eslint/no-floating-promises"])).toBe(2);
    },
    LINT_TIMEOUT_MS,
  );
});

describe("destructuring reads are not sinks (PR #3 follow-up 3)", () => {
  it.each([
    [
      "inner_html_js",
      JS_PATH,
      `export function f(el) {
  const { innerHTML } = el;
  return innerHTML;
}
`,
    ],
    [
      "srcdoc_js",
      JS_PATH,
      `export function f(fr) {
  const { srcdoc } = fr;
  return srcdoc;
}
`,
    ],
    [
      "inner_html_tsx",
      TSX_PATH,
      `export function f(el: Element): string {
  const { innerHTML } = el;
  return innerHTML;
}
`,
    ],
    [
      "srcdoc_tsx",
      TSX_PATH,
      `export function f(fr: HTMLIFrameElement): string {
  const { srcdoc } = fr;
  return srcdoc;
}
`,
    ],
  ] as const)(
    "test_lint_destructuring_read_%s_has_no_restricted_syntax_error",
    async (_name, filePath, code) => {
      const messages = await lint(code, filePath);
      expect(fatalOrIgnored(messages)).toEqual([]);
      expect(errorLines(messages, RESTRICTED)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );
});

describe("more sink forms in JS files (PR #3 follow-ups 4, 5)", () => {
  it.each([
    [
      "content_document_write",
      `export function f(fr, x) {
  fr.contentDocument.write(x); // sink
}
`,
    ],
    [
      "template_literal_inner_html_assignment",
      `export function f(el, x) {
  el[\`innerHTML\`] = x; // sink
}
`,
    ],
    [
      "template_literal_srcdoc_object_key",
      `export function f(x) {
  return { [\`srcdoc\`]: x }; // sink
}
`,
    ],
    [
      "template_literal_set_attribute_srcdoc",
      `export function f(fr, x) {
  fr.setAttribute(\`srcdoc\`, x); // sink
}
`,
    ],
  ] as const)(
    "test_lint_js_%s_reports_no_restricted_syntax_error",
    async (_name, code) => {
      const messages = await lint(code, JS_PATH);
      expect(fatalOrIgnored(messages)).toEqual([]);
      expect(errorLines(messages, RESTRICTED)).toContain(sinkLine(code));
    },
    LINT_TIMEOUT_MS,
  );
});
