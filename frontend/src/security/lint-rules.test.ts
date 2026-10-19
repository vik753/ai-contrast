// @vitest-environment node
/**
 * S1-T2 AC6 / threat model T1 browser control 5 —
 * ESLint forbids `dangerouslySetInnerHTML` (rule `no-restricted-syntax`).
 *
 * Lints code strings with the ESLint Node API against the real
 * `frontend/eslint.config.js`, using the virtual path `src/__lint_fixture__.tsx`.
 */
import { fileURLToPath } from "node:url";
import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND_DIR = fileURLToPath(new URL("../../", import.meta.url));
const FIXTURE_PATH = "src/__lint_fixture__.tsx";
const RULE = "no-restricted-syntax";
const LINT_TIMEOUT_MS = 60_000;

const UNSAFE_COMPONENT = `export function Unsafe({ html }: { html: string }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
`;

const UNSAFE_NESTED_COMPONENT = `export function UnsafeNested({ html }: { html: string }) {
  return (
    <section>
      <p>{html.length}</p>
      <span dangerouslySetInnerHTML={{ __html: html }}></span>
    </section>
  );
}
`;

const SAFE_COMPONENT = `export function Safe({ text }: { text: string }) {
  return <div>{text}</div>;
}
`;

async function lint(code: string): Promise<Linter.LintMessage[]> {
  const eslint = new ESLint({ cwd: FRONTEND_DIR });
  const results = await eslint.lintText(code, { filePath: FIXTURE_PATH });
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

/** Parse errors and "file ignored" warnings have `ruleId === null`. */
function linterProblems(messages: Linter.LintMessage[]): Linter.LintMessage[] {
  return messages.filter((m) => m.fatal === true || m.ruleId === null);
}

describe("ESLint dangerouslySetInnerHTML rule (AC6)", () => {
  it(
    "test_lint_component_with_dangerously_set_inner_html_reports_error",
    async () => {
      const messages = await lint(UNSAFE_COMPONENT);
      expect(linterProblems(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages)).toHaveLength(1);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_nested_dangerously_set_inner_html_reports_error",
    async () => {
      const messages = await lint(UNSAFE_NESTED_COMPONENT);
      expect(linterProblems(messages)).toEqual([]);
      expect(restrictedSyntaxErrors(messages)).toHaveLength(1);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_error_points_to_dangerously_set_inner_html_line",
    async () => {
      const messages = await lint(UNSAFE_COMPONENT);
      const [error] = restrictedSyntaxErrors(messages);
      expect(error?.line).toBe(2);
    },
    LINT_TIMEOUT_MS,
  );

  it(
    "test_lint_component_without_dangerously_set_inner_html_has_no_restricted_syntax_error",
    async () => {
      const messages = await lint(SAFE_COMPONENT);
      expect(linterProblems(messages)).toEqual([]);
      expect(messages.filter((m) => m.ruleId === RULE)).toEqual([]);
    },
    LINT_TIMEOUT_MS,
  );
});
