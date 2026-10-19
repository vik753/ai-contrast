import i18next from "i18next";
import { I18nextProvider, useTranslation } from "react-i18next";
import { LanguageSwitcher } from "./components/LanguageSwitcher";
import { RatingIcon, type Rating } from "./components/RatingIcon";
import { SOURCE_CODE_URL } from "./config";

const RATINGS: readonly Rating[] = ["green", "yellow", "red"];

function Shell() {
  const { t } = useTranslation();

  return (
    <div className="layout">
      <header className="site-header">
        <div className="container site-header__inner">
          <p className="brand">{t("app.title")}</p>
          <LanguageSwitcher />
        </div>
      </header>

      <main className="container site-main">
        <section className="intro" aria-labelledby="intro-title">
          <h1 id="intro-title" className="intro__title">
            {t("home.tagline")}
          </h1>
          <p className="intro__lead">{t("home.description")}</p>
        </section>

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
