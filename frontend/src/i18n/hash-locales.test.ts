// @vitest-environment node
/**
 * S4-T1 AC4, AC5 — new messages exist in `en`, `uk` and `ru`.
 * Key names are not fixed: keys are found by the English copy of the task,
 * and the error by a key path segment equal to its code (`duplicate_file`).
 */
import { describe, expect, it } from "vitest";
import { flattenLocale } from "../test/locale-utils";
import { keyContaining, pluralBase } from "../test/upload-fakes";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";

const EN = flattenLocale(en);
const OTHER = { uk: flattenLocale(uk), ru: flattenLocale(ru) } as const;

const PHRASES = [
  "The same file is in Contract",
  "Same text as another file in this contract",
  "Same text as a file in Contract",
] as const;

const PLACEHOLDER = /\{\{\s*\w+\s*\}\}/g;

describe("hash messages", () => {
  it.each(PHRASES)("test_en_has_a_value_with_%j", (phrase) => {
    expect(() => keyContaining(EN, phrase)).not.toThrow();
  });

  it.each(PHRASES)("test_uk_and_ru_translate_the_value_with_%j", (phrase) => {
    const key = keyContaining(EN, phrase);
    for (const locale of Object.values(OTHER)) {
      const forms = Object.keys(locale).filter((k) => pluralBase(k) === pluralBase(key));
      expect(forms.length).toBeGreaterThan(0);
      for (const form of forms) {
        expect(locale[form]).not.toBe(EN[key]);
      }
    }
  });

  it.each(["The same file is in Contract", "Same text as a file in Contract"])(
    "test_uk_and_ru_keep_the_contract_placeholder_in_%j",
    (phrase) => {
      const key = keyContaining(EN, phrase);
      const expected = String(EN[key]).match(PLACEHOLDER) ?? [];
      expect(expected.length).toBeGreaterThan(0);
      for (const locale of Object.values(OTHER)) {
        expect(String(locale[key]).match(PLACEHOLDER)).toEqual(expected);
      }
    },
  );

  it("test_duplicate_file_error_exists_and_is_translated_in_all_locales", () => {
    const keysOf = (l: Record<string, unknown>): string[] =>
      Object.keys(l).filter((k) => k.split(".").includes("duplicate_file"));
    const enKeys = keysOf(EN);
    expect(enKeys.length).toBeGreaterThan(0);
    for (const locale of Object.values(OTHER)) {
      for (const key of enKeys) {
        expect(typeof locale[key]).toBe("string");
        expect(locale[key]).not.toBe(EN[key]);
      }
    }
  });
});
