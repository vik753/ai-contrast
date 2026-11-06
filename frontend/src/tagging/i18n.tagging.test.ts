/** S8-T3 AC — every tagging string exists in en, uk, ru; no HTML sinks in `src/tagging`. */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "../i18n/locales/en.json";
import ru from "../i18n/locales/ru.json";
import uk from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";
import { TAG_ERROR_CODES } from "./tagApi";

const E = flattenLocale(en);
const U = flattenLocale(uk);
const R = flattenLocale(ru);
const keysOf = (l: Record<string, unknown>) =>
  Object.keys(l).filter((k) => k.startsWith("tagging."));

const REQUIRED = [
  "title",
  "start",
  "noTopics",
  "pair",
  "cost",
  "risk.label",
  "other.heading",
  "counts",
  "flag.model_tags_dropped",
  "flag.not_analyzed.too_many_clauses",
  "missing.heading",
  "layer2.heuristic",
  "layer2.high",
  "add.label",
  "add.button",
  "add.clauseCap",
  "removeTag",
  ...["pending", "running", "done", "failed"].map((s) => `status.${s}`),
  ...["keyword", "model", "check", "client"].map((s) => `source.${s}`),
  ...["bad_output", "timeout", "quota", "check_failed", "clause_cap"].map((r) => `incomplete.${r}`),
  ...[...TAG_ERROR_CODES, "digest_mismatch", "network", "unknown"].map((c) => `error.${c}`),
].map((k) => `tagging.${k}`);

describe("tagging locales", () => {
  it.each([
    ["en", E],
    ["uk", U],
    ["ru", R],
  ] as const)("test_%s_has_every_required_key", (_n, l) => {
    for (const k of REQUIRED) expect(typeof l[k], k).toBe("string");
    expect(keysOf(l).sort()).toEqual(keysOf(E).sort());
  });

  it("test_uk_and_ru_are_translated_not_copied_from_en", () => {
    for (const k of ["tagging.start", "tagging.source.keyword", "tagging.error.busy"]) {
      expect(U[k], k).not.toBe(E[k]);
      expect(R[k], k).not.toBe(E[k]);
    }
  });

  it("test_placeholders_match_in_every_language", () => {
    for (const k of ["tagging.pair", "tagging.cost", "tagging.counts", "tagging.removeTag"]) {
      const ph = (v: unknown) => (String(v).match(/\{\{\w+\}\}/g) ?? []).sort();
      expect(ph(U[k]), k).toEqual(ph(E[k]));
      expect(ph(R[k]), k).toEqual(ph(E[k]));
    }
  });
});

describe("tagging sources", () => {
  const dir = __dirname;
  const files = readdirSync(dir).filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."));
  it("test_no_html_sinks_in_tagging_sources", () => {
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) {
      const src = readFileSync(join(dir, f), "utf8");
      expect(src, f).not.toMatch(
        /dangerouslySetInnerHTML|innerHTML|insertAdjacentHTML|document\.write/,
      );
    }
  });
});
