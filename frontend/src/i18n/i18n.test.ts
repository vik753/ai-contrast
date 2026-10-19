/**
 * S1-T2 — unit tests for the public interface of `src/i18n/index.ts`.
 * Covers AC2, AC3 and AC4 at module level (no rendering).
 *
 * The module is re-imported for every test (`vi.resetModules`) so that any
 * module-level state (cached promise, instance) does not leak between tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  makeGetItemThrow,
  makeLocalStorageAccessThrow,
  makeSetItemThrow,
  resetBrowserEnv,
  setBrowserLanguage,
} from "../test/browser-env";

type I18nModule = typeof import("./index");

async function freshModule(): Promise<I18nModule> {
  vi.resetModules();
  return import("./index");
}

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  resetBrowserEnv();
});

describe("constants", () => {
  it("test_supported_languages_are_en_uk_ru_in_order", async () => {
    const { SUPPORTED_LANGUAGES } = await freshModule();
    expect([...SUPPORTED_LANGUAGES]).toEqual(["en", "uk", "ru"]);
  });

  it("test_language_storage_key_is_aic_lang", async () => {
    const { LANGUAGE_STORAGE_KEY } = await freshModule();
    expect(LANGUAGE_STORAGE_KEY).toBe("aic.lang");
  });
});

describe("setupI18n — default language (AC2)", () => {
  it("test_setup_with_empty_storage_selects_english", async () => {
    const { setupI18n } = await freshModule();
    const instance = await setupI18n();
    expect(instance.language).toBe("en");
  });

  it.each(["uk-UA", "ru-RU", "de-DE"])(
    "test_setup_with_browser_language_%s_and_empty_storage_selects_english",
    async (browserLanguage) => {
      setBrowserLanguage(browserLanguage);
      const { setupI18n } = await freshModule();
      const instance = await setupI18n();
      expect(instance.language).toBe("en");
      expect(document.documentElement.lang).toBe("en");
    },
  );
});

describe("setupI18n — stored language (AC3)", () => {
  it.each(["en", "uk", "ru"] as const)(
    "test_setup_with_stored_%s_selects_it",
    async (lang) => {
      localStorage.setItem("aic.lang", lang);
      setBrowserLanguage("de-DE");
      const { setupI18n } = await freshModule();
      const instance = await setupI18n();
      expect(instance.language).toBe(lang);
    },
  );

  it.each(["de", "", "english", "EN-us", "<script>alert(1)</script>", "null"])(
    "test_setup_with_invalid_stored_value_%j_falls_back_to_english",
    async (stored) => {
      localStorage.setItem("aic.lang", stored);
      const { setupI18n } = await freshModule();
      const instance = await setupI18n();
      expect(instance.language).toBe("en");
      expect(document.documentElement.lang).toBe("en");
    },
  );

  it("test_setup_when_getitem_throws_resolves_with_english", async () => {
    makeGetItemThrow();
    const { setupI18n } = await freshModule();
    const instance = await setupI18n();
    expect(instance.language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("test_setup_when_localstorage_access_throws_resolves_with_english", async () => {
    makeLocalStorageAccessThrow();
    const { setupI18n } = await freshModule();
    const instance = await setupI18n();
    expect(instance.language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("<html lang> (AC4)", () => {
  it("test_setup_sets_html_lang_to_en_by_default", async () => {
    const { setupI18n } = await freshModule();
    await setupI18n();
    expect(document.documentElement.lang).toBe("en");
  });

  it.each(["uk", "ru"] as const)(
    "test_setup_with_stored_%s_sets_html_lang",
    async (lang) => {
      localStorage.setItem("aic.lang", lang);
      const { setupI18n } = await freshModule();
      await setupI18n();
      expect(document.documentElement.lang).toBe(lang);
    },
  );

  it.each(["uk", "ru", "en"] as const)(
    "test_change_language_to_%s_sets_html_lang",
    async (lang) => {
      const { setupI18n, changeLanguage } = await freshModule();
      await setupI18n();
      if (lang === "en") {
        await changeLanguage("ru");
      }
      await changeLanguage(lang);
      expect(document.documentElement.lang).toBe(lang);
    },
  );
});

describe("changeLanguage (AC3)", () => {
  it.each(["uk", "ru", "en"] as const)(
    "test_change_language_to_%s_switches_i18n_language",
    async (lang) => {
      const { setupI18n, changeLanguage } = await freshModule();
      const instance = await setupI18n();
      await changeLanguage(lang);
      expect(instance.language).toBe(lang);
    },
  );

  it.each(["uk", "ru", "en"] as const)(
    "test_change_language_to_%s_stores_choice_under_aic_lang",
    async (lang) => {
      const { setupI18n, changeLanguage } = await freshModule();
      await setupI18n();
      await changeLanguage(lang);
      expect(localStorage.getItem("aic.lang")).toBe(lang);
    },
  );

  it("test_stored_choice_is_used_by_next_setup", async () => {
    const first = await freshModule();
    await first.setupI18n();
    await first.changeLanguage("ru");

    resetHtmlLangOnly();
    const second = await freshModule();
    const instance = await second.setupI18n();
    expect(instance.language).toBe("ru");
    expect(document.documentElement.lang).toBe("ru");
  });

  it("test_change_language_when_setitem_throws_still_switches", async () => {
    const { setupI18n, changeLanguage } = await freshModule();
    const instance = await setupI18n();
    makeSetItemThrow();
    await expect(changeLanguage("uk")).resolves.toBeUndefined();
    expect(instance.language).toBe("uk");
    expect(document.documentElement.lang).toBe("uk");
  });

  it("test_change_language_when_localstorage_access_throws_still_switches", async () => {
    makeLocalStorageAccessThrow();
    const { setupI18n, changeLanguage } = await freshModule();
    const instance = await setupI18n();
    await expect(changeLanguage("ru")).resolves.toBeUndefined();
    expect(instance.language).toBe("ru");
    expect(document.documentElement.lang).toBe("ru");
  });
});

function resetHtmlLangOnly(): void {
  document.documentElement.removeAttribute("lang");
}
