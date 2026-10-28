/** S5b-T3 AC 5: the new `pseudo.*` keys exist in en, uk and ru, with the same placeholders. */
import { describe, expect, it } from "vitest";
import { flattenLocale } from "../test/locale-utils";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";

const CLASSES = [
  "ORG",
  "PERSON",
  "TAX_ID",
  "ACCOUNT",
  "ADDRESS",
  "PHONE",
  "EMAIL",
  "URL",
  "PERSONAL_DOC",
  "DOC_NO",
  "VEHICLE",
  "SIGNATURE",
  "HEALTH",
];
const ERRORS = [
  "detector_version_mismatch",
  "input_not_clean",
  "invalid_placeholder",
  "invalid_request",
  "request_too_large",
  "busy",
  "safety_timeout",
  "network_error",
  "invalid_response",
  "timeout",
  "unmasked_identifier",
  "too_many_identifiers",
];
export const KEYS = [
  "pseudo.checkReplacements",
  "pseudo.everythingCorrect",
  "pseudo.unmaskAll",
  "pseudo.unmaskOne",
  "pseudo.cannotUnmask",
  "pseudo.maskSelection",
  "pseudo.maskClassLabel",
  "pseudo.maskAllEqual",
  "pseudo.maskOnlyThis",
  "pseudo.status.notReviewed",
  "pseudo.status.ready",
  "pseudo.status.confirmAgain",
  "pseudo.neutralized.explanation",
  "pseudo.requisites.dropped",
  "pseudo.requisites.kept",
  "upload.preview.warning.requisites_condition",
  "upload.preview.warning.placeholder_lookalike",
  "upload.preview.warning.masked_next_to_amount",
  ...CLASSES.map((c) => `pseudo.class.${c}`),
  ...ERRORS.map((c) => `pseudo.error.${c}`),
];

const locales = { en: flattenLocale(en), uk: flattenLocale(uk), ru: flattenLocale(ru) };
const vars = (s: string) => (s.match(/\{\{\w+\}\}/g) ?? []).sort().join(",");

describe("pseudo locale keys", () => {
  for (const [name, flat] of Object.entries(locales)) {
    it.each(KEYS)(`test_${name}_has_key_%s`, (key) => {
      expect(typeof flat[key]).toBe("string");
      expect((flat[key] as string).trim()).not.toBe("");
    });
  }

  it("test_maskAllEqual_has_a_count_in_every_language", () => {
    for (const flat of Object.values(locales)) {
      expect(String(flat["pseudo.maskAllEqual"])).toContain("{{count}}");
    }
  });

  it.each(KEYS)("test_placeholders_match_across_languages_%s", (key) => {
    const e = vars(String(locales.en[key]));
    expect(vars(String(locales.uk[key]))).toBe(e);
    expect(vars(String(locales.ru[key]))).toBe(e);
  });

  it("test_uk_and_ru_are_translated_not_copied", () => {
    for (const key of [
      "pseudo.everythingCorrect",
      "pseudo.checkReplacements",
      "pseudo.cannotUnmask",
    ]) {
      expect(locales.uk[key]).not.toBe(locales.en[key]);
      expect(locales.ru[key]).not.toBe(locales.en[key]);
    }
  });
});
