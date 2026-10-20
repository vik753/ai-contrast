// @vitest-environment node
/**
 * S1-T2c AC1, AC2 / threat model T1 — the HTML-sink lint rule
 * (`no-restricted-syntax`) covers every JS/TS extension and the extra sink
 * forms found in review.
 *
 * Code strings are linted with the ESLint Node API against the real config.
 * Each fixture marks its sink line with a trailing `// sink` comment.
 */
import { fileURLToPath } from "node:url";
import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND_DIR = fileURLToPath(new URL("../../", import.meta.url));
const RULE = "no-restricted-syntax";
const LINT_TIMEOUT_MS = 60_000;

let eslintInstance: ESLint | undefined;

async function lint(code: string, filePath: string): Promise<Linter.LintMessage[]> {
  eslintInstance ??= new ESLint({ cwd: FRONTEND_DIR });
  const results = await eslintInstance.lintText(code, { filePath });
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

function restrictedSyntaxLines(messages: Linter.LintMessage[]): number[] {
  return messages.filter((m) => m.ruleId === RULE && m.severity === 2).map((m) => m.line);
}

function fatalMessages(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.fatal === true);
}

/** "File ignored" warnings have `ruleId === null` and are not fatal. */
function ignoredWarnings(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.ruleId === null && m.fatal !== true);
}

const TS_SINK = `export function f(el: Element, html: string): void {
  el.innerHTML = html; // sink
}
`;

const JS_SINK = `export function f(el, html) {
  el.innerHTML = html; // sink
}
`;

describe("HTML-sink rule applies to every JS/TS extension (S1-T2c AC1)", () => {
  it.each([
    ["mts", "src/__lint_fixture__.mts", TS_SINK],
    ["cts", "src/__lint_fixture__.cts", TS_SINK],
    ["mjs", "src/__lint_fixture__.mjs", JS_SINK],
    ["cjs", "src/__lint_fixture__.cjs", JS_SINK],
    ["js", "src/__lint_fixture__.js", JS_SINK],
    ["jsx", "src/__lint_fixture__.jsx", JS_SINK],
    ["ts", "src/__lint_fixture__.ts", TS_SINK],
    ["tsx", "src/__lint_fixture__.tsx", TS_SINK],
  ] as const)(
    "test_lint_inner_html_assignment_in_%s_file_reports_no_restricted_syntax_error",
    async (_ext, filePath, code) => {
      const messages = await lint(code, filePath);
      expect(fatalMessages(messages)).toEqual([]);
      expect(ignoredWarnings(messages)).toEqual([]);
      expect(restrictedSyntaxLines(messages)).toContain(sinkLine(code));
    },
    LINT_TIMEOUT_MS,
  );
});

const TSX_PATH = "src/__lint_fixture__.tsx";

const EXTRA_SINKS: readonly (readonly [string, string])[] = [
  [
    "srcdoc_assignment",
    `export function f(fr: HTMLIFrameElement, html: string): void {
  fr.srcdoc = html; // sink
}
`,
  ],
  [
    "object_assign_inner_html",
    `export function f(el: Element, html: string): void {
  Object.assign(el, { innerHTML: html }); // sink
}
`,
  ],
  [
    "object_assign_outer_html",
    `export function f(el: Element, html: string): void {
  Object.assign(el, { outerHTML: html }); // sink
}
`,
  ],
  [
    "object_assign_srcdoc",
    `export function f(fr: HTMLIFrameElement, html: string): void {
  Object.assign(fr, { srcdoc: html }); // sink
}
`,
  ],
  [
    "create_element_iframe_src_doc_prop",
    `import { createElement, type ReactElement } from "react";

export function f(html: string): ReactElement {
  return createElement("iframe", { srcDoc: html }); // sink
}
`,
  ],
  [
    "insert_adjacent_html_call",
    `export function f(el: Element, html: string): void {
  el.insertAdjacentHTML.call(el, "beforeend", html); // sink
}
`,
  ],
  [
    "insert_adjacent_html_reference",
    `export function f(el: Element): unknown {
  const g = el.insertAdjacentHTML; // sink
  return g;
}
`,
  ],
  [
    "create_contextual_fragment_call",
    `export function f(range: Range, html: string): DocumentFragment {
  return range.createContextualFragment.call(range, html); // sink
}
`,
  ],
  [
    "set_attribute_srcdoc",
    `export function f(fr: HTMLIFrameElement, html: string): void {
  fr.setAttribute("srcdoc", html); // sink
}
`,
  ],
  [
    "set_attribute_onclick",
    `export function f(el: Element, code: string): void {
  el.setAttribute("onclick", code); // sink
}
`,
  ],
  [
    "set_attribute_onerror",
    `export function f(el: Element, code: string): void {
  el.setAttribute("onerror", code); // sink
}
`,
  ],
  [
    "new_window_dom_parser",
    `export function f(): DOMParser {
  return new window.DOMParser(); // sink
}
`,
  ],
  [
    "window_document_write",
    `export function f(html: string): void {
  window.document.write(html); // sink
}
`,
  ],
  [
    "document_computed_write",
    `export function f(html: string): void {
  document["write"](html); // sink
}
`,
  ],
];

describe("extra HTML-sink forms (S1-T2c AC2)", () => {
  it.each(EXTRA_SINKS)(
    "test_lint_sink_%s_reports_no_restricted_syntax_error",
    async (_name, code) => {
      const messages = await lint(code, TSX_PATH);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxLines(messages)).toContain(sinkLine(code));
    },
    LINT_TIMEOUT_MS,
  );

  it.each(EXTRA_SINKS)(
    "test_lint_sink_%s_message_cites_t1",
    async (_name, code) => {
      const messages = await lint(code, TSX_PATH);
      const errors = messages.filter((m) => m.ruleId === RULE && m.severity === 2);
      expect(errors.length).toBeGreaterThanOrEqual(1);
      for (const error of errors) {
        expect(error.message).toMatch(/\bT1\b/);
      }
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_set_attribute_class_has_no_errors",
    async () => {
      const code = `export function f(el: Element): void {
  el.setAttribute("class", "x");
}
`;
      const messages = await lint(code, TSX_PATH);
      expect(fatalMessages(messages)).toEqual([]);
      expect(messages.filter((m) => m.severity === 2)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_set_attribute_title_and_data_attribute_have_no_restricted_syntax_error",
    async () => {
      const code = `export function f(el: Element, text: string): void {
  el.setAttribute("title", text);
  el.setAttribute("data-one", text);
}
`;
      const messages = await lint(code, TSX_PATH);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxLines(messages)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );
});
