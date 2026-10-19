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

describe("locale key parity (AC7)", () => {
  it.each(["uk", "ru"] as const)("test_%s_has_same_keys_as_en", (name) => {
    expect(sortedKeys(name)).toEqual(sortedKeys("en"));
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
      const untranslated = TRANSLATED_KEYS.filter(
        (key) => LOCALES[name][key] === LOCALES.en[key],
      );
      expect(untranslated).toEqual([]);
    },
  );

  it("test_uk_and_ru_tagline_differ", () => {
    expect(LOCALES.uk["home.tagline"]).not.toBe(LOCALES.ru["home.tagline"]);
  });
});
