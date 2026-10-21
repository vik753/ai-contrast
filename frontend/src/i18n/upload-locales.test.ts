// @vitest-environment node
/**
 * S2-T2 AC11 — upload form strings in `en`, `uk` and `ru`.
 *
 * Key names are not fixed by the task. The tests find keys by the English
 * copy quoted in the acceptance criteria, and error messages by a key path
 * segment equal to the error code (for example `upload.errors.busy`).
 * Key parity (with plural folding) is in `locales.test.ts`.
 */
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";
import { flattenLocale, type FlatLocale } from "../test/locale-utils";
import { PLURAL_SUFFIX, keyContaining, pluralBase } from "../test/upload-fakes";

const EN = flattenLocale(en);
const UK = flattenLocale(uk);
const RU = flattenLocale(ru);
const TRANSLATIONS = { uk: UK, ru: RU } as const;

/** English copy quoted in S2-T2 AC1, AC7 and AC9. */
const AC_PHRASES = [
  "Add contract",
  "Waiting",
  "Checking…",
  "Word document",
  "Text file",
  "Save the file as .docx or PDF and try again",
  "Export to PDF: File → Export To → PDF",
  "Add at least one file to each contract",
  "Checking files…",
  "Ready to compare:",
] as const;

/** Every code the form can show: server codes, client-only codes, client checks. */
const ERROR_CODES = [
  "length_required",
  "file_too_large",
  "unsupported_media_type",
  "empty_file",
  "unsupported_type",
  "legacy_office_unsupported",
  "pages_unsupported",
  "archive_rejected",
  "busy",
  "request_too_large",
  "network_error",
  "timeout",
  "aborted",
  "unknown_error",
  "too_many_files",
  "total_too_large",
] as const;

function keysForCode(locale: FlatLocale, code: string): string[] {
  return Object.keys(locale).filter((key) => key.split(".").includes(code));
}

describe("AC11 — new strings exist and are translated", () => {
  it.each(AC_PHRASES)("test_en_has_a_value_with_%j", (phrase) => {
    expect(() => keyContaining(EN, phrase)).not.toThrow();
  });

  it.each(AC_PHRASES)("test_uk_and_ru_translate_the_value_with_%j", (phrase) => {
    const key = keyContaining(EN, phrase);
    for (const locale of Object.values(TRANSLATIONS)) {
      const base = pluralBase(key);
      const forms = Object.keys(locale).filter((k) => pluralBase(k) === base);
      expect(forms.length).toBeGreaterThan(0);
      for (const form of forms) {
        expect(locale[form]).not.toBe(EN[key]);
      }
    }
  });

  it.each(ERROR_CODES)("test_en_has_a_message_for_code_%s", (code) => {
    expect(keysForCode(EN, code).length).toBeGreaterThan(0);
  });

  it("test_en_has_a_contract_heading_template", () => {
    const templates = Object.values(EN).filter(
      (v) => typeof v === "string" && /^Contract \{\{\s*\w+\s*\}\}$/.test(v),
    );
    expect(templates).toHaveLength(1);
  });

  it("test_en_has_an_add_files_to_contract_template", () => {
    const templates = Object.values(EN).filter(
      (v) => typeof v === "string" && /^Add files to Contract \{\{\s*\w+\s*\}\}$/.test(v),
    );
    expect(templates).toHaveLength(1);
  });

  it("test_privacy_note_says_not_stored_and_names_stay_in_browser", () => {
    const notes = Object.values(EN).filter(
      (v) => typeof v === "string" && /not stored/i.test(v) && /file names/i.test(v),
    );
    expect(notes.length).toBeGreaterThan(0);
  });
});

describe("AC11 — plural forms", () => {
  it("test_ready_line_is_a_plural_key_with_count", () => {
    const key = keyContaining(EN, "Ready to compare:");
    expect(key).toMatch(/_other$/);
    expect(String(EN[key])).toContain("{{count}}");
    expect(`${pluralBase(key)}_one` in EN).toBe(true);
  });

  it("test_every_en_plural_key_has_one_and_other", () => {
    const bases = new Set(
      Object.keys(EN)
        .filter((k) => PLURAL_SUFFIX.test(k))
        .map(pluralBase),
    );
    expect(bases.size).toBeGreaterThan(0);
    for (const base of bases) {
      expect([`${base}_one`, `${base}_other`].filter((k) => !(k in EN))).toEqual([]);
    }
  });

  it.each(["uk", "ru"] as const)("test_%s_plural_keys_have_one_few_many_other", (name) => {
    const locale = TRANSLATIONS[name];
    const bases = new Set(
      Object.keys(EN)
        .filter((k) => PLURAL_SUFFIX.test(k))
        .map(pluralBase),
    );
    for (const base of bases) {
      const missing = ["one", "few", "many", "other"]
        .map((form) => `${base}_${form}`)
        .filter((k) => !(k in locale));
      expect(missing).toEqual([]);
    }
  });

  it.each(["uk", "ru"] as const)("test_%s_plural_forms_use_count", (name) => {
    const locale = TRANSLATIONS[name];
    const pluralKeys = Object.keys(locale).filter((k) => PLURAL_SUFFIX.test(k));
    for (const key of pluralKeys) {
      expect(String(locale[key])).toContain("{{count}}");
    }
  });
});

describe("AC11 — home.status", () => {
  const OLD_STATUS = {
    en: "Early version: contract comparison is coming soon.",
    uk: "Рання версія: порівняння договорів з’явиться незабаром.",
    ru: "Ранняя версия: сравнение договоров скоро появится.",
  } as const;
  const LOCALES = { en: EN, uk: UK, ru: RU } as const;

  it.each(["en", "uk", "ru"] as const)("test_%s_home_status_is_updated", (name) => {
    const value = LOCALES[name]["home.status"];
    expect(typeof value).toBe("string");
    expect(value).not.toBe(OLD_STATUS[name]);
  });

  it("test_en_home_status_mentions_adding_contracts_and_comparison_later", () => {
    const value = String(EN["home.status"]);
    expect(value).toMatch(/add/i);
    expect(value).toMatch(/compar/i);
  });

  it.each(["uk", "ru"] as const)("test_%s_home_status_is_translated", (name) => {
    expect(TRANSLATIONS[name]["home.status"]).not.toBe(EN["home.status"]);
  });
});
