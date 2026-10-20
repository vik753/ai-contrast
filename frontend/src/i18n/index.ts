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

/**
 * Marker on the i18next singleton. This module can be loaded more than once
 * (tests reset the module registry) while i18next stays the same object, so a
 * module-level flag is not enough to keep the listener unique.
 */
const HTML_LANG_LISTENER = Symbol.for("ai-contrast.i18n.html-lang-listener");

/**
 * `<html lang>` follows every language change, including direct
 * `i18next.changeLanguage()` calls. Registered once per i18next instance.
 */
function syncHtmlLangOnChange(instance: i18n): void {
  if (Reflect.get(instance, HTML_LANG_LISTENER) === true) {
    return;
  }
  instance.on("languageChanged", () => {
    const resolved = instance.resolvedLanguage;
    setDocumentLanguage(isLanguage(resolved) ? resolved : DEFAULT_LANGUAGE);
  });
  Reflect.set(instance, HTML_LANG_LISTENER, true);
}

async function initOrSwitch(lang: Language): Promise<void> {
  syncHtmlLangOnChange(i18next);
  if (i18next.isInitialized) {
    await i18next.changeLanguage(lang);
    return;
  }
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

/** Initializes i18n with the stored language (English if none or invalid). */
export async function setupI18n(): Promise<i18n> {
  const lang = readStoredLanguage();
  await initOrSwitch(lang);
  setDocumentLanguage(lang);
  return i18next;
}

/**
 * Last-resort setup used when `setupI18n()` failed: English, no storage.
 * Never rejects; `<html lang>` is always set to English.
 */
export async function setupFallbackI18n(): Promise<i18n> {
  try {
    await initOrSwitch(DEFAULT_LANGUAGE);
  } catch {
    // Nothing else to try: the app still renders; i18next falls back to keys.
  }
  setDocumentLanguage(DEFAULT_LANGUAGE);
  return i18next;
}

/**
 * Switches the language and stores the choice. `<html lang>` is updated by
 * the `languageChanged` listener only, so a switch writes it once. Works
 * without a prior `setupI18n()`: it sets i18n up first.
 */
export async function changeLanguage(lang: Language): Promise<void> {
  const next = isLanguage(lang) ? lang : DEFAULT_LANGUAGE;
  if (!i18next.isInitialized) {
    await setupI18n();
  }
  syncHtmlLangOnChange(i18next);
  await i18next.changeLanguage(next);
  storeLanguage(next);
}
