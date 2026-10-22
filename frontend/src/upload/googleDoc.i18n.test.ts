/**
 * S3-T6b items 1 and 6 — locale keys for the Google Docs link, in en, uk, ru.
 * These tests fail until the keys are added to the three locale files.
 */
import { describe, expect, it } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";

const LOCALES = { en: flattenLocale(enJson), uk: flattenLocale(ukJson), ru: flattenLocale(ruJson) };

const EN_TEXT: Record<string, string> = {
  "upload.google.label": "Google Docs link",
  "upload.google.add": "Add",
  "upload.google.hint":
    "Share the document as “Anyone with the link can view”. For a private document, download it as DOCX or PDF and upload the file.",
  "upload.google.invalid": "This is not a Google Docs document link.",
  "upload.google.duplicate": "This document is already added.",
  "upload.google.name": "Google Docs document …{{suffix}}",
};

const NEW_CODES = [
  "invalid_request",
  "invalid_google_doc_id",
  "google_doc_not_public",
  "google_doc_not_found",
  "google_doc_too_large",
  "google_doc_unavailable",
  "google_doc_timeout",
];

function value(locale: Record<string, unknown>, key: string): string | undefined {
  const v = locale[key];
  if (typeof v === "string") {
    return v;
  }
  // An error entry may be an object with `reason` and `detail`.
  const reason = locale[`${key}.reason`];
  return typeof reason === "string" ? reason : undefined;
}

describe("English copy", () => {
  it.each(Object.entries(EN_TEXT))("test_en_%s_has_the_given_text", (key, expected) => {
    expect(LOCALES.en[key]).toBe(expected);
  });
});

describe("keys exist in uk and ru", () => {
  it.each(
    Object.keys(EN_TEXT).flatMap(
      (key) =>
        [
          ["uk", key],
          ["ru", key],
        ] as const,
    ),
  )("test_%s_has_key_%s_translated", (lang, key) => {
    const text = LOCALES[lang][key];
    expect(typeof text).toBe("string");
    expect((text as string).trim()).not.toBe("");
    if (key !== "upload.google.name") {
      expect(text).not.toBe(EN_TEXT[key]);
    }
  });

  it.each(["uk", "ru"] as const)("test_%s_name_template_keeps_suffix_placeholder", (lang) => {
    expect(String(LOCALES[lang]["upload.google.name"])).toContain("{{suffix}}");
  });
});

describe("error messages for new codes", () => {
  it.each(
    NEW_CODES.flatMap(
      (code) =>
        [
          ["en", code],
          ["uk", code],
          ["ru", code],
        ] as const,
    ),
  )("test_%s_has_error_message_for_%s", (lang, code) => {
    const text = value(LOCALES[lang], `upload.errors.${code}`);
    expect(text).toBeDefined();
    expect((text ?? "").trim()).not.toBe("");
  });

  it.each(
    NEW_CODES.flatMap(
      (code) =>
        [
          ["uk", code],
          ["ru", code],
        ] as const,
    ),
  )("test_%s_error_for_%s_differs_from_english", (lang, code) => {
    expect(value(LOCALES[lang], `upload.errors.${code}`)).not.toBe(
      value(LOCALES.en, `upload.errors.${code}`),
    );
  });
});
