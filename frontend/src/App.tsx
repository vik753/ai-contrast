import i18next from "i18next";
import { useEffect, useId, useState } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";
import type { SafetyDocument } from "./api/safetyCheck";
import { LanguageSwitcher } from "./components/LanguageSwitcher";
import { RatingIcon, type Rating } from "./components/RatingIcon";
import { SOURCE_CODE_URL } from "./config";
import { getKey } from "./provider/keyStore";
import { ProviderSettings, type ProviderChoice } from "./provider/ProviderSettings";
import { TopicPanel } from "./topics/TopicPanel";
import { SettingsPanel } from "./settings/SettingsPanel";
import { startupCleanup } from "./storage/historySetting";
import { UploadForm } from "./upload/UploadForm";

const RATINGS: readonly Rating[] = ["green", "yellow", "red"];

const NO_DOCUMENTS: readonly SafetyDocument[] = [];

/** The key is read from storage at render time; it is never kept in React state. */
function keyOf(provider: string): { key?: string } {
  if (provider === "free") return {};
  const key = getKey(provider);
  return key === null || key === "" ? {} : { key };
}

function Shell() {
  const { t } = useTranslation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const panelId = useId();
  const topicsId = useId();
  const [topicsOpen, setTopicsOpen] = useState(false);
  const [choice, setChoice] = useState<ProviderChoice>({ provider: "free" });

  useEffect(() => {
    void startupCleanup();
  }, []);

  return (
    <div className="layout">
      <header className="site-header">
        <div className="container site-header__inner">
          <p className="brand">{t("app.title")}</p>
          <div className="site-header__actions">
            <button
              type="button"
              className="button button--quiet button--small"
              aria-expanded={settingsOpen}
              aria-controls={settingsOpen ? panelId : undefined}
              onClick={() => {
                setSettingsOpen((open) => !open);
              }}
            >
              {t("settings.open")}
            </button>
            <LanguageSwitcher />
          </div>
        </div>
      </header>

      <main className="container site-main">
        <section className="intro" aria-labelledby="intro-title">
          <h1 id="intro-title" className="intro__title">
            {t("home.tagline")}
          </h1>
          <p className="intro__lead">{t("home.description")}</p>
        </section>

        {settingsOpen ? <SettingsPanel id={panelId} /> : null}

        <ProviderSettings onChoiceChange={setChoice} />

        <div className="card">
          <button
            type="button"
            className="button button--quiet"
            aria-expanded={topicsOpen}
            aria-controls={topicsOpen ? topicsId : undefined}
            onClick={() => {
              setTopicsOpen((open) => !open);
            }}
          >
            {t("topics.open")}
          </button>
        </div>
        {topicsOpen ? (
          <div id={topicsId}>
            <TopicPanel
              connection={{ ...choice, ...keyOf(choice.provider) }}
              documents={NO_DOCUMENTS}
            />
          </div>
        ) : null}

        <UploadForm />

        <section className="card" aria-labelledby="ratings-title">
          <h2 id="ratings-title" className="card__title">
            {t("home.ratings.title")}
          </h2>
          <ul className="ratings">
            {RATINGS.map((rating) => (
              <li key={rating} className={`ratings__item ratings__item--${rating}`}>
                <RatingIcon rating={rating} />
                <span className="ratings__text">
                  <strong className="ratings__label">{t(`home.ratings.${rating}.label`)}</strong>
                  <span className="ratings__description">
                    {t(`home.ratings.${rating}.description`)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="card__note">{t("home.ratings.evidence")}</p>
        </section>

        <p className="note">{t("home.byok")}</p>
        <p className="status">{t("home.status")}</p>
      </main>

      <footer className="site-footer">
        <div className="container site-footer__inner">
          <p className="site-footer__privacy">{t("footer.privacy")}</p>
          <p className="site-footer__meta">
            <a className="site-footer__link" href={SOURCE_CODE_URL} rel="noopener noreferrer">
              {t("footer.source")}
            </a>
            <span className="site-footer__license">{t("footer.license")}</span>
          </p>
        </div>
      </footer>
    </div>
  );
}

/** App shell. Call `setupI18n()` before the first render. */
export default function App() {
  return (
    <I18nextProvider i18n={i18next}>
      <Shell />
    </I18nextProvider>
  );
}
