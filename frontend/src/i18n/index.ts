/**
 * Interface language setup.
 *
 * - English is the default on first visit, whatever the browser language is
 *   (no language detector on purpose).
 * - The user's choice is stored in `localStorage` under `aic.lang`.
 *   Storage may be missing, blocked or full: every access is guarded and
 *   failures fall back to English (read) or are ignored (write).
 * - `<html lang>` always follows the current language.
 *
 * `setupI18n()` works on the global i18next instance and may be called more
 * than once (tests re-import this module): a second call only re-applies the
 * stored language.
 */
import i18next, { type i18n } from "i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";

export const SUPPORTED_LANGUAGES = ["en", "uk", "ru"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "en";
export const LANGUAGE_STORAGE_KEY = "aic.lang";

const resources = {
  en: { translation: en },
  uk: { translation: uk },
  ru: { translation: ru },
} as const;

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

function readStoredLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(stored) ? stored : DEFAULT_LANGUAGE;
  } catch {
    // Blocked or broken storage: use the default language.
    return DEFAULT_LANGUAGE;
  }
}

function storeLanguage(lang: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  } catch {
    // Blocked or full storage: the choice is kept for this page only.
  }
}

function setDocumentLanguage(lang: Language): void {
  document.documentElement.lang = lang;
}

export async function setupI18n(): Promise<i18n> {
  const lang = readStoredLanguage();
  if (i18next.isInitialized) {
    await i18next.changeLanguage(lang);
  } else {
    await i18next.init({
      resources,
      lng: lang,
      fallbackLng: DEFAULT_LANGUAGE,
      supportedLngs: [...SUPPORTED_LANGUAGES],
      load: "currentOnly",
      defaultNS: "translation",
      // React escapes all rendered text; i18next must not escape it twice.
      interpolation: { escapeValue: false },
      // Resources are bundled, so nothing loads asynchronously.
      react: { useSuspense: false },
    });
  }
  setDocumentLanguage(lang);
  return i18next;
}

export async function changeLanguage(lang: Language): Promise<void> {
  const next = isLanguage(lang) ? lang : DEFAULT_LANGUAGE;
  await i18next.changeLanguage(next);
  setDocumentLanguage(next);
  storeLanguage(next);
}
