/**
 * S3-T5 AC5, AC6 — OCR warning texts and i18n keys (en, uk, ru).
 *
 * Assumed keys: `upload.ocr.progress` ("Recognizing page {{current}} of
 * {{total}}…"), `upload.preview.warning.ocr_used`,
 * `upload.preview.warning.ocr_low_confidence`,
 * `upload.errors.too_many_ocr_pages`, `upload.errors.ocr_failed`.
 * `warningKey(code)` maps the two new warning codes to their own keys.
 */
import { describe, expect, it } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";
import { groupWarnings, warningKey } from "./Preview";

const LOCALES = { en: flattenLocale(enJson), uk: flattenLocale(ukJson), ru: flattenLocale(ruJson) };

const KEYS = [
  "upload.ocr.progress",
  "upload.preview.warning.ocr_used",
  "upload.preview.warning.ocr_low_confidence",
  "upload.errors.too_many_ocr_pages",
  "upload.errors.ocr_failed",
] as const;

describe("warning codes", () => {
  it("test_warning_key_maps_ocr_used_to_its_own_key", () => {
    expect(warningKey("ocr_used")).toBe("upload.preview.warning.ocr_used");
  });

  it("test_warning_key_maps_ocr_low_confidence_to_its_own_key", () => {
    expect(warningKey("ocr_low_confidence")).toBe("upload.preview.warning.ocr_low_confidence");
  });

  it("test_group_warnings_lists_pages_of_low_confidence", () => {
    const groups = groupWarnings([
      { code: "ocr_low_confidence", page: 4 },
      { code: "ocr_low_confidence", page: 2 },
      { code: "ocr_used", page: 2 },
    ]);
    expect(groups).toEqual([
      { key: "upload.preview.warning.ocr_low_confidence", pages: [2, 4] },
      { key: "upload.preview.warning.ocr_used", pages: [2] },
    ]);
  });
});

describe.each(Object.entries(LOCALES))("locale %s", (code, locale) => {
  it.each(KEYS)("test_%s_is_a_non_empty_string", (key) => {
    const value = locale[key];
    expect(typeof value === "string" && value.trim() !== "", `${code}: ${key}`).toBe(true);
  });

  it("test_progress_text_has_current_and_total_placeholders", () => {
    const value = String(locale["upload.ocr.progress"]);
    expect(value).toMatch(/\{\{\s*current\s*\}\}/);
    expect(value).toMatch(/\{\{\s*total\s*\}\}/);
  });
});

describe("translations", () => {
  it("test_english_progress_text_is_the_spec_text", () => {
    expect(LOCALES.en["upload.ocr.progress"]).toBe("Recognizing page {{current}} of {{total}}…");
  });

  it.each(["uk", "ru"] as const)("test_%s_texts_are_translated", (code) => {
    for (const key of KEYS) {
      expect(LOCALES[code][key], `${code}: ${key}`).not.toBe(LOCALES.en[key]);
      expect(String(LOCALES[code][key])).toMatch(/[А-Яа-яІіЇїЄє]/);
    }
  });
});
