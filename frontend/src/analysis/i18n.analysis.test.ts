/** S9-T4 — every analysis string exists in en, uk, ru. */
import { describe, expect, it } from "vitest";
import en from "../i18n/locales/en.json";
import ru from "../i18n/locales/ru.json";
import uk from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";
import { ANALYZE_ERROR_CODES } from "./analyzeApi";

const E = flattenLocale(en);
const U = flattenLocale(uk);
const R = flattenLocale(ru);
const keysOf = (l: Record<string, unknown>) =>
  Object.keys(l).filter((k) => k.startsWith("analysis."));

const REASONS = [
  "quote_too_short",
  "suspicious_span",
  "check_exceptions",
  "global_override",
  "too_many_references",
  "unresolved_reference",
  "number_mismatch",
  "document_flags",
  "other_not_green",
  "unverified",
  "incomplete",
];
const REQUIRED = [
  "title",
  "start",
  "stop",
  "explanationWithheld",
  "unverified",
  "compareYourself",
  "other.heading",
  "other.unrated",
  "incompleteNotice",
  ...["pending", "running", "done", "incomplete", "failed", "stopped"].map((s) => `status.${s}`),
  ...["ok", "model_tags_dropped", "not_analyzed"].map((s) => `topic.state.${s}`),
  ...["too_many_clauses", "topic_call_cap", "bad_output", "timeout", "budget"].map(
    (s) => `topic.reason.${s}`,
  ),
  ...["green", "yellow", "red"].map((s) => `rating.${s}`),
  ...REASONS.map((s) => `reason.${s}`),
  ...["not_confirmed", "not_stated", "not_analyzed"].map((s) => `value.${s}`),
  ...["better", "worse", "same", "different"].map((s) => `mark.${s}`),
  ...["unit", "type", "too_few"].map((s) => `notComparable.${s}`),
  ...["yellow", "red"].map((s) => `missing.${s}`),
  ...[
    ...ANALYZE_ERROR_CODES,
    "digest_mismatch",
    "network",
    "stream_invalid",
    "aborted",
    "unknown",
  ].map((c) => `error.${c}`),
].map((k) => `analysis.${k}`);

describe("analysis locales", () => {
  it.each([
    ["en", E],
    ["uk", U],
    ["ru", R],
  ] as const)("test_%s_has_every_required_key", (_n, l) => {
    for (const k of REQUIRED) expect(typeof l[k], k).toBe("string");
    expect(keysOf(l).sort()).toEqual(keysOf(E).sort());
  });

  it("test_uk_and_ru_are_translated_not_copied_from_en", () => {
    for (const k of [
      "analysis.start",
      "analysis.stop",
      "analysis.rating.red",
      "analysis.error.busy",
    ]) {
      expect(U[k], k).not.toBe(E[k]);
      expect(R[k], k).not.toBe(E[k]);
    }
  });

  it("test_placeholders_match_in_every_language", () => {
    for (const k of ["analysis.other.unrated"]) {
      const ph = (v: unknown) => (String(v).match(/\{\{\w+\}\}/g) ?? []).sort();
      expect(ph(U[k]), k).toEqual(ph(E[k]));
      expect(ph(R[k]), k).toEqual(ph(E[k]));
    }
  });

  it("test_rating_label_text_is_not_just_a_colour_word_alone_in_en", () => {
    for (const c of ["green", "yellow", "red"])
      expect(String(E[`analysis.rating.${c}`]).length).toBeGreaterThan(3);
  });
});
