// @vitest-environment node
/**
 * S1-T2 AC7 — locale files have the same keys and only non-empty strings.
 */
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";
import { flattenLocale } from "../test/locale-utils";

const LOCALES = {
  en: flattenLocale(en),
  uk: flattenLocale(uk),
  ru: flattenLocale(ru),
} as const;

type LocaleName = keyof typeof LOCALES;
const NAMES: LocaleName[] = ["en", "uk", "ru"];

const REQUIRED_KEYS = [
  "app.title",
  "home.tagline",
  "language.label",
  "footer.source",
  "footer.privacy",
] as const;

/** Keys whose text must really be translated (not a copy of English). */
const TRANSLATED_KEYS = [
  "home.tagline",
  "language.label",
  "footer.source",
  "footer.privacy",
] as const;

function sortedKeys(name: LocaleName): string[] {
  return Object.keys(LOCALES[name]).sort();
}

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/**
 * Keys with i18next plural suffixes folded to their base key. English has
 * `_one`/`_other`, Ukrainian and Russian also `_few`/`_many` (S2-T2 AC11),
 * so parity with English is checked on base keys.
 */
function baseKeys(name: LocaleName): string[] {
  return [...new Set(Object.keys(LOCALES[name]).map((k) => k.replace(PLURAL_SUFFIX, "")))].sort();
}

describe("locale key parity (AC7)", () => {
  it.each(["uk", "ru"] as const)("test_%s_has_same_keys_as_en", (name) => {
    expect(baseKeys(name)).toEqual(baseKeys("en"));
  });

  it("test_uk_and_ru_have_identical_keys_including_plural_forms", () => {
    expect(sortedKeys("uk")).toEqual(sortedKeys("ru"));
  });

  it("test_en_locale_is_not_empty", () => {
    expect(sortedKeys("en").length).toBeGreaterThan(0);
  });
});

describe("locale values (AC7)", () => {
  it.each(NAMES)("test_%s_every_value_is_non_empty_string", (name) => {
    const bad = Object.entries(LOCALES[name])
      .filter(([, value]) => typeof value !== "string" || value.trim() === "")
      .map(([key]) => key);
    expect(bad).toEqual([]);
  });

  it.each(NAMES)("test_%s_contains_required_contract_keys", (name) => {
    const missing = REQUIRED_KEYS.filter((key) => !(key in LOCALES[name]));
    expect(missing).toEqual([]);
  });

  it.each(NAMES)("test_%s_app_title_is_ai_contrast", (name) => {
    expect(LOCALES[name]["app.title"]).toBe("AI Contrast");
  });

  it.each(["uk", "ru"] as const)(
    "test_%s_translates_user_visible_keys_differently_from_en",
    (name) => {
      const untranslated = TRANSLATED_KEYS.filter((key) => LOCALES[name][key] === LOCALES.en[key]);
      expect(untranslated).toEqual([]);
    },
  );

  it("test_uk_and_ru_tagline_differ", () => {
    expect(LOCALES.uk["home.tagline"]).not.toBe(LOCALES.ru["home.tagline"]);
  });
});

/**
 * S1-T2b AC13 (ADR 0007) — `home.byok` describes both paths (free built-in
 * model or own key). The exact wording is approved by the customer, so the
 * tests check only presence, parity and that the old key-only copy is gone.
 */
const OLD_BYOK: Record<LocaleName, string> = {
  en: "You use your own AI provider API key. Contract text goes only to the provider you choose.",
  uk: "Ви використовуєте власний API-ключ постачальника ШІ. Текст договору надходить лише до обраного вами постачальника.",
  ru: "Вы используете собственный API-ключ провайдера ИИ. Текст договора передаётся только выбранному вами провайдеру.",
};

describe("home.byok copy (S1-T2b AC13)", () => {
  it.each(NAMES)("test_%s_has_non_empty_home_byok", (name) => {
    const value = LOCALES[name]["home.byok"];
    expect(typeof value).toBe("string");
    expect(String(value).trim()).not.toBe("");
  });

  it.each(NAMES)("test_%s_home_byok_replaces_old_key_only_copy", (name) => {
    expect(LOCALES[name]["home.byok"]).not.toBe(OLD_BYOK[name]);
  });

  it.each(["uk", "ru"] as const)("test_%s_home_byok_is_translated", (name) => {
    expect(LOCALES[name]["home.byok"]).not.toBe(LOCALES.en["home.byok"]);
  });
});
