import i18next from "i18next";
import { useTranslation } from "react-i18next";
import type { Lang } from "./types";

/** `useTranslation` bound to the global i18next instance, plus the UI language. */
export function useT() {
  const { t, i18n } = useTranslation(undefined, { i18n: i18next });
  const current = i18n.resolvedLanguage ?? i18n.language;
  const lang: Lang = current === "uk" || current === "ru" ? current : "en";
  return { t, lang };
}
