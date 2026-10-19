// @vitest-environment node
/**
 * S1-T2b AC1, AC2 / threat model T1 — every raw HTML sink is banned by the
 * real ESLint config (`no-restricted-syntax`), and inline `eslint-disable`
 * comments cannot hide the error (`linterOptions.noInlineConfig: true`).
 *
 * Code strings are linted with the ESLint Node API and the virtual path
 * `src/__lint_fixture__.tsx`.
 */
import { fileURLToPath } from "node:url";
import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND_DIR = fileURLToPath(new URL("../../", import.meta.url));
const FIXTURE_PATH = "src/__lint_fixture__.tsx";
const RULE = "no-restricted-syntax";
const LINT_TIMEOUT_MS = 60_000;

let eslintInstance: ESLint | undefined;

async function lint(code: string): Promise<Linter.LintMessage[]> {
  eslintInstance ??= new ESLint({ cwd: FRONTEND_DIR });
  const results = await eslintInstance.lintText(code, { filePath: FIXTURE_PATH });
  expect(results).toHaveLength(1);
  const [result] = results;
  if (!result) {
    throw new Error("ESLint returned no result");
  }
  return result.messages;
}

function restrictedSyntaxErrors(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.ruleId === RULE && m.severity === 2);
}

function fatalMessages(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.fatal === true);
}

/**
 * One fixture per sink from S1-T2b AC1. Each fixture is valid TSX and contains
 * exactly one sink on line `sinkLine` (1-based).
 */
interface SinkCase {
  name: string;
  code: string;
  sinkLine: number;
}

const SINKS: readonly SinkCase[] = [
  {
    name: "jsx_attribute_dangerously_set_inner_html",
    code: `export function F({ h }: { h: { __html: string } }) {
  return <div dangerouslySetInnerHTML={h} />;
}
`,
    sinkLine: 2,
  },
  {
    name: "object_property_dangerously_set_inner_html_identifier_key",
    code: `export function f(h: unknown): object {
  return { dangerouslySetInnerHTML: h };
}
`,
    sinkLine: 2,
  },
  {
    name: "object_property_dangerously_set_inner_html_string_key",
    code: `export function f(h: unknown): object {
  return { "dangerouslySetInnerHTML": h };
}
`,
    sinkLine: 2,
  },
  {
    name: "member_access_dangerously_set_inner_html",
    code: `export function f(props: { dangerouslySetInnerHTML?: unknown }): unknown {
  return props.dangerouslySetInnerHTML;
}
`,
    sinkLine: 2,
  },
  {
    name: "property___html",
    code: `export function f(text: string): object {
  return { __html: text };
}
`,
    sinkLine: 2,
  },
  {
    name: "assignment_to_inner_html",
    code: `export function f(el: Element, text: string): void {
  el.innerHTML = text;
}
`,
    sinkLine: 2,
  },
  {
    name: "compound_assignment_to_inner_html",
    code: `export function f(el: Element, text: string): void {
  el.innerHTML += text;
}
`,
    sinkLine: 2,
  },
  {
    name: "assignment_to_outer_html",
    code: `export function f(el: Element, text: string): void {
  el.outerHTML = text;
}
`,
    sinkLine: 2,
  },
  {
    name: "call_insert_adjacent_html",
    code: `export function f(el: Element, text: string): void {
  el.insertAdjacentHTML("beforeend", text);
}
`,
    sinkLine: 2,
  },
  {
    name: "call_create_contextual_fragment",
    code: `export function f(range: Range, text: string): DocumentFragment {
  return range.createContextualFragment(text);
}
`,
    sinkLine: 2,
  },
  {
    name: "call_set_html_unsafe",
    code: `export function f(el: { setHTMLUnsafe(t: string): void }, text: string): void {
  el.setHTMLUnsafe(text);
}
`,
    sinkLine: 2,
  },
  {
    name: "call_parse_html_unsafe",
    code: `export function f(doc: { parseHTMLUnsafe(t: string): unknown }, text: string): unknown {
  return doc.parseHTMLUnsafe(text);
}
`,
    sinkLine: 2,
  },
  {
    name: "call_document_write",
    code: `export function f(text: string): void {
  document.write(text);
}
`,
    sinkLine: 2,
  },
  {
    name: "call_document_writeln",
    code: `export function f(text: string): void {
  document.writeln(text);
}
`,
    sinkLine: 2,
  },
  {
    name: "new_dom_parser",
    code: `export function f(): unknown {
  return new DOMParser();
}
`,
    sinkLine: 2,
  },
  {
    name: "jsx_attribute_src_doc_camel_case",
    code: `export function F({ text }: { text: string }) {
  return <iframe title="x" srcDoc={text} />;
}
`,
    sinkLine: 2,
  },
  {
    name: "jsx_attribute_srcdoc_lower_case",
    code: `export function F({ text }: { text: string }) {
  return <iframe title="x" srcdoc={text} />;
}
`,
    sinkLine: 2,
  },
];

/** `[name, case]` tuples so that `%s` puts the sink name into the test title. */
const SINK_CASES = SINKS.map((sink) => [sink.name, sink] as const);

describe("raw HTML sinks are banned by lint (S1-T2b AC1)", () => {
  it.each(SINK_CASES)(
    "test_lint_sink_%s_reports_no_restricted_syntax_error",
    async (_name, { code }) => {
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages).length).toBeGreaterThanOrEqual(1);
    },
    LINT_TIMEOUT_MS,
  );

  it.each(SINK_CASES)(
    "test_lint_sink_%s_error_is_on_sink_line",
    async (_name, { code, sinkLine }) => {
      const messages = await lint(code);
      const lines = restrictedSyntaxErrors(messages).map((m) => m.line);
      expect(lines).toContain(sinkLine);
    },
    LINT_TIMEOUT_MS,
  );

  it.each(SINK_CASES)(
    "test_lint_sink_%s_message_cites_t1",
    async (_name, { code }) => {
      const messages = await lint(code);
      const errors = restrictedSyntaxErrors(messages);
      expect(errors.length).toBeGreaterThanOrEqual(1);
      for (const error of errors) {
        expect(error.message).toMatch(/\bT1\b/);
      }
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_clean_component_has_no_restricted_syntax_error",
    async () => {
      const code = `export function Clean({ text }: { text: string }) {
  return (
    <section>
      <p title={text}>{text}</p>
    </section>
  );
}
`;
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(messages.filter((m) => m.ruleId === RULE)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_clean_plain_text_dom_code_has_no_errors",
    async () => {
      const code = `export function setPlainText(el: Element, text: string): void {
  el.textContent = text;
}

export function readPlainText(el: Element): string {
  return el.textContent;
}
`;
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(messages.filter((m) => m.severity === 2)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );
});

describe("inline config cannot disable the rule (S1-T2b AC2)", () => {
  it(
    "test_eslint_disable_next_line_does_not_hide_no_restricted_syntax_error",
    async () => {
      const code = `export function F({ h }: { h: { __html: string } }) {
  // eslint-disable-next-line no-restricted-syntax
  return <div dangerouslySetInnerHTML={h} />;
}
`;
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages).map((m) => m.line)).toContain(3);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_file_level_eslint_disable_does_not_hide_no_restricted_syntax_error",
    async () => {
      const code = `/* eslint-disable */
export function f(el: Element, text: string): void {
  el.innerHTML = text;
}
`;
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages).map((m) => m.line)).toContain(3);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_eslint_disable_line_does_not_hide_no_restricted_syntax_error",
    async () => {
      const code = `export function f(text: string): void {
  document.write(text); // eslint-disable-line no-restricted-syntax
}
`;
      const messages = await lint(code);
      expect(fatalMessages(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages).map((m) => m.line)).toContain(2);
    },
    LINT_TIMEOUT_MS,
  );
});
