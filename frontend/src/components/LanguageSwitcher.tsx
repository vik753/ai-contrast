import { useTranslation } from "react-i18next";
import { changeLanguage, SUPPORTED_LANGUAGES, type Language } from "../i18n";

/** Short codes shown on the buttons. They are the same in every language. */
const LANGUAGE_CODES: Record<Language, string> = {
  en: "EN",
  uk: "UK",
  ru: "RU",
};

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const current = i18n.resolvedLanguage ?? i18n.language;

  return (
    <div role="group" aria-label={t("language.label")} className="lang-switcher">
      {SUPPORTED_LANGUAGES.map((lang) => (
        <button
          key={lang}
          type="button"
          className="lang-switcher__button"
          aria-pressed={current === lang}
          title={t(`language.names.${lang}`)}
          onClick={() => {
            void changeLanguage(lang);
          }}
        >
          {LANGUAGE_CODES[lang]}
        </button>
      ))}
    </div>
  );
}
