/**
 * S5-T2 AC2 — every new message exists in en, uk and ru.
 * Key names: `upload.errors.<code>`; the other copy is found by its English
 * value (key names are free) and must exist with a translated value.
 */
import { describe, expect, it } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";

const EN = flattenLocale(enJson);
const UK = flattenLocale(ukJson);
const RU = flattenLocale(ruJson);

const NEW_CODES = [
  "too_many_clauses",
  "clause_too_long",
  "segment_timeout",
  "segment_failed",
  "invalid_response",
];

describe("segment error messages", () => {
  it.each(NEW_CODES)("test_error_%s_exists_in_en_uk_ru", (code) => {
    const key = `upload.errors.${code}`;
    for (const locale of [EN, UK, RU]) {
      expect(typeof locale[key]).toBe("string");
      expect((locale[key] as string).length).toBeGreaterThan(10);
    }
    expect(UK[key]).not.toBe(EN[key]);
    expect(RU[key]).not.toBe(EN[key]);
  });

  it.each(NEW_CODES)("test_error_%s_does_not_show_the_raw_code", (code) => {
    for (const locale of [EN, UK, RU]) {
      expect(locale[`upload.errors.${code}`]).not.toContain(code);
    }
  });
});

describe("row and preview copy", () => {
  it.each([["Splitting into clauses…"], ["Try again"], ["Clauses"], ["Text"]])(
    "test_english_value_%s_has_translations_under_the_same_key",
    (value) => {
      const keys = Object.entries(EN)
        .filter(([key, v]) => key.startsWith("upload.") && v === value)
        .map(([key]) => key);
      expect(keys.length).toBe(1);
      const [key = ""] = keys;
      expect(typeof UK[key]).toBe("string");
      expect(typeof RU[key]).toBe("string");
      expect(UK[key]).not.toBe(value);
      expect(RU[key]).not.toBe(value);
    },
  );
});
