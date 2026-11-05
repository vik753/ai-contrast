/** S7-T3 — every topic string exists in en, uk, ru; no hard-coded UI text or HTML sinks. */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "../i18n/locales/en.json";
import ru from "../i18n/locales/ru.json";
import uk from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";

const E = flattenLocale(en);
const U = flattenLocale(uk);
const R = flattenLocale(ru);
const topicKeys = (l: Record<string, unknown>) =>
  Object.keys(l).filter((k) => k.startsWith("topics."));

const CODES = [
  "topic_contains_identifier",
  "topic_flagged",
  "invalid_topic_text",
  "ai_bad_output",
  "free_quota_exhausted",
  "busy",
  "catalog_version_mismatch",
  "rate_limited",
  "free_pass_invalid",
  "free_pass_expired",
  "free_pass_exhausted",
  "turnstile_failed",
  "network",
  "unknown",
];
const REQUIRED = [
  "title",
  "domain.label",
  "domain.none",
  "side.label",
  "templates.heading",
  "suggest.button",
  "suggest.accept",
  "suggest.dropped",
  "own.heading",
  "own.name",
  "own.description",
  "own.propose",
  "own.confirm",
  "attr.list",
  "attr.label",
  "attr.direction",
  "attr.remove",
  "persist.label",
  "export.button",
  "import.label",
  ...["none", "lower_better", "higher_better", "more_better", "fewer_better", "ordered"].map(
    (d) => `direction.${d}`,
  ),
  ...["too_large", "invalid_json", "forbidden_key", "invalid_shape", "tooLong"].map(
    (c) => `import.error.${c}`,
  ),
  ...CODES.map((c) => `error.${c}`),
].map((k) => `topics.${k}`);

describe("topics locales", () => {
  it.each([
    ["en", E],
    ["uk", U],
    ["ru", R],
  ] as const)("test_%s_has_every_required_key", (_n, l) => {
    for (const k of REQUIRED) expect(typeof l[k], k).toBe("string");
    expect(topicKeys(l).sort()).toEqual(topicKeys(E).sort());
  });

  it("test_uk_and_ru_are_translated_not_copied", () => {
    for (const k of REQUIRED) {
      const e = String(E[k]);
      if (e.length <= 4) continue;
      expect(String(U[k]), `uk ${k}`).not.toBe(e);
      expect(String(R[k]), `ru ${k}`).not.toBe(e);
    }
  });

  it("test_dropped_message_has_count_placeholder_in_all_languages", () => {
    for (const l of [E, U, R]) expect(String(l["topics.suggest.dropped"])).toContain("{{count}}");
  });
});

describe("topics sources", () => {
  const files = readdirSync(__dirname).filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."));
  it("test_sources_exist", () => {
    expect(files).toEqual(
      expect.arrayContaining(["api.ts", "topicStore.ts", "transfer.ts", "TopicPanel.tsx"]),
    );
  });
  it.each(files)("test_%s_has_no_html_sink_and_no_literal_jsx_text", (f) => {
    const src = readFileSync(join(__dirname, f), "utf8");
    expect(src).not.toMatch(/dangerouslySetInnerHTML|innerHTML|insertAdjacentHTML|document\.write/);
    if (f.endsWith(".tsx")) expect(src).not.toMatch(/>\s*[A-Za-z][A-Za-z ,.!?'-]{2,}\s*</);
  });
});
