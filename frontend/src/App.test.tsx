/**
 * S1-T2 — rendering tests for the app shell.
 * Covers AC1, AC2, AC3, AC4, AC5 and the runtime part of AC7.
 *
 * Every test re-imports `src/i18n/index.ts` and `src/App.tsx`
 * (`vi.resetModules`) and calls `setupI18n()` before rendering, as the
 * contract says: "App expects i18n to be set up".
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enJson from "./i18n/locales/en.json";
import ruJson from "./i18n/locales/ru.json";
import ukJson from "./i18n/locales/uk.json";
import {
  makeGetItemThrow,
  makeLocalStorageAccessThrow,
  makeSetItemThrow,
  resetBrowserEnv,
  setBrowserLanguage,
} from "./test/browser-env";
import { allStrings, flattenLocale, text, type FlatLocale } from "./test/locale-utils";

const REPO_URL = "https://github.com/vik753/ai-contrast";
const LANG_BUTTONS = ["EN", "UK", "RU"] as const;
type LangButton = (typeof LANG_BUTTONS)[number];

const LOCALE: Record<"en" | "uk" | "ru", FlatLocale> = {
  en: flattenLocale(enJson),
  uk: flattenLocale(ukJson),
  ru: flattenLocale(ruJson),
};
const EN = LOCALE.en;
const UK = LOCALE.uk;
const RU = LOCALE.ru;

async function renderApp(): Promise<void> {
  vi.resetModules();
  const i18nModule = await import("./i18n/index");
  await i18nModule.setupI18n();
  const appModule: { default: ComponentType } = await import("./App");
  const App = appModule.default;
  render(<App />);
  // Wait until the shell is on screen (covers lazy init or Suspense).
  await screen.findByRole("main");
}

function languageGroup(locale: FlatLocale = EN): HTMLElement {
  return screen.getByRole("group", { name: text(locale, "language.label") });
}

function langButton(name: LangButton, locale: FlatLocale = EN): HTMLElement {
  return within(languageGroup(locale)).getByRole("button", { name });
}

async function switchTo(name: LangButton, from: FlatLocale, to: FlatLocale): Promise<void> {
  fireEvent.click(langButton(name, from));
  await screen.findByText(text(to, "home.tagline"));
}

function footer(): HTMLElement {
  return screen.getByRole("contentinfo");
}

/** Asserts that the visible UI text matches `locale`. */
function expectUiIn(locale: FlatLocale): void {
  expect(within(screen.getByRole("banner")).getByText(text(locale, "app.title"))).toBeTruthy();
  expect(within(screen.getByRole("main")).getByText(text(locale, "home.tagline"))).toBeTruthy();
  expect(languageGroup(locale)).toBeTruthy();
  expect(
    within(footer()).getByRole("link", { name: text(locale, "footer.source") }),
  ).toBeTruthy();
  expect(within(footer()).getByText(text(locale, "footer.privacy"))).toBeTruthy();
}

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  cleanup();
  resetBrowserEnv();
});

describe("AC1 — page layout", () => {
  it("test_header_shows_app_title_ai_contrast", async () => {
    await renderApp();
    const header = screen.getByRole("banner");
    expect(within(header).getByText("AI Contrast")).toBeTruthy();
  });

  it("test_language_switcher_group_is_labelled_by_language_label", async () => {
    await renderApp();
    expect(languageGroup()).toBeTruthy();
  });

  it("test_language_switcher_has_exactly_en_uk_ru_buttons", async () => {
    await renderApp();
    const buttons = within(languageGroup()).getAllByRole("button");
    expect(buttons).toHaveLength(3);
    for (const name of LANG_BUTTONS) {
      expect(langButton(name)).toBeTruthy();
    }
  });

  it("test_main_area_shows_home_tagline", async () => {
    await renderApp();
    const main = screen.getByRole("main");
    expect(within(main).getByText(text(EN, "home.tagline"))).toBeTruthy();
  });

  it("test_footer_exists", async () => {
    await renderApp();
    expect(footer()).toBeTruthy();
  });
});

describe("AC2 — English by default", () => {
  it.each(["uk-UA", "ru-RU"])(
    "test_first_visit_with_browser_language_%s_renders_english",
    async (browserLanguage) => {
      setBrowserLanguage(browserLanguage);
      await renderApp();
      expectUiIn(EN);
    },
  );

  it("test_first_visit_marks_en_button_pressed", async () => {
    setBrowserLanguage("uk-UA");
    await renderApp();
    expect(langButton("EN").getAttribute("aria-pressed")).toBe("true");
    expect(langButton("UK").getAttribute("aria-pressed")).toBe("false");
    expect(langButton("RU").getAttribute("aria-pressed")).toBe("false");
  });
});

describe("AC3 — language switching", () => {
  it("test_click_uk_shows_ukrainian_texts", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    expectUiIn(UK);
  });

  it("test_click_uk_removes_english_tagline", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    expect(screen.queryByText(text(EN, "home.tagline"))).toBeNull();
    expect(screen.queryByText(text(EN, "footer.privacy"))).toBeNull();
  });

  it("test_click_uk_then_ru_shows_russian_texts", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    await switchTo("RU", UK, RU);
    expectUiIn(RU);
    expect(screen.queryByText(text(UK, "home.tagline"))).toBeNull();
  });

  it("test_click_ru_then_en_shows_english_texts_again", async () => {
    await renderApp();
    await switchTo("RU", EN, RU);
    await switchTo("EN", RU, EN);
    expectUiIn(EN);
  });

  it("test_click_uk_sets_aria_pressed_on_uk_only", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    expect(langButton("UK", UK).getAttribute("aria-pressed")).toBe("true");
    expect(langButton("EN", UK).getAttribute("aria-pressed")).toBe("false");
    expect(langButton("RU", UK).getAttribute("aria-pressed")).toBe("false");
  });

  it("test_click_ru_after_uk_moves_aria_pressed_to_ru", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    await switchTo("RU", UK, RU);
    expect(langButton("RU", RU).getAttribute("aria-pressed")).toBe("true");
    expect(langButton("UK", RU).getAttribute("aria-pressed")).toBe("false");
    expect(langButton("EN", RU).getAttribute("aria-pressed")).toBe("false");
  });

  it("test_click_uk_then_ru_stores_choice_under_aic_lang", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    await waitFor(() => expect(localStorage.getItem("aic.lang")).toBe("uk"));
    await switchTo("RU", UK, RU);
    await waitFor(() => expect(localStorage.getItem("aic.lang")).toBe("ru"));
  });

  it.each([
    ["uk", UK, "UK"],
    ["ru", RU, "RU"],
  ] as const)(
    "test_stored_language_%s_is_used_on_setup",
    async (stored, locale, button) => {
      localStorage.setItem("aic.lang", stored);
      setBrowserLanguage("en-US");
      await renderApp();
      expectUiIn(locale);
      expect(langButton(button, locale).getAttribute("aria-pressed")).toBe("true");
    },
  );

  it.each(["de", "xx", "<img src=x onerror=alert(1)>"])(
    "test_invalid_stored_value_%j_falls_back_to_english",
    async (stored) => {
      localStorage.setItem("aic.lang", stored);
      await renderApp();
      expectUiIn(EN);
      expect(langButton("EN").getAttribute("aria-pressed")).toBe("true");
    },
  );

  it("test_getitem_throwing_does_not_break_setup", async () => {
    makeGetItemThrow();
    await renderApp();
    expectUiIn(EN);
  });

  it("test_getitem_and_setitem_throwing_do_not_break_switching", async () => {
    makeGetItemThrow();
    makeSetItemThrow();
    await renderApp();
    await switchTo("UK", EN, UK);
    expectUiIn(UK);
    await switchTo("RU", UK, RU);
    expectUiIn(RU);
    expect(document.documentElement.lang).toBe("ru");
  });

  it("test_blocked_localstorage_access_does_not_break_setup_or_switching", async () => {
    makeLocalStorageAccessThrow();
    await renderApp();
    expectUiIn(EN);
    await switchTo("RU", EN, RU);
    expectUiIn(RU);
  });
});

describe("AC4 — <html lang> follows the language", () => {
  it("test_html_lang_is_en_after_setup", async () => {
    await renderApp();
    expect(document.documentElement.lang).toBe("en");
  });

  it("test_html_lang_follows_clicks_uk_ru_en", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    await waitFor(() => expect(document.documentElement.lang).toBe("uk"));
    await switchTo("RU", UK, RU);
    await waitFor(() => expect(document.documentElement.lang).toBe("ru"));
    await switchTo("EN", RU, EN);
    await waitFor(() => expect(document.documentElement.lang).toBe("en"));
  });

  it("test_html_lang_matches_stored_language_on_setup", async () => {
    localStorage.setItem("aic.lang", "uk");
    await renderApp();
    expect(document.documentElement.lang).toBe("uk");
  });
});

describe("AC5 — footer source link and privacy note", () => {
  function sourceLink(): HTMLElement {
    return within(footer()).getByRole("link", { name: text(EN, "footer.source") });
  }

  it("test_footer_source_link_has_footer_source_name", async () => {
    await renderApp();
    expect(sourceLink()).toBeTruthy();
  });

  it("test_footer_source_link_points_to_repository", async () => {
    await renderApp();
    expect(sourceLink().getAttribute("href")).toBe(REPO_URL);
  });

  it("test_footer_source_link_rel_contains_noopener_and_noreferrer", async () => {
    await renderApp();
    const rel = (sourceLink().getAttribute("rel") ?? "").split(/\s+/);
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
  });

  it("test_footer_shows_privacy_note", async () => {
    await renderApp();
    expect(within(footer()).getByText(text(EN, "footer.privacy"))).toBeTruthy();
  });

  it("test_footer_source_link_keeps_url_after_language_switch", async () => {
    await renderApp();
    await switchTo("RU", EN, RU);
    const link = within(footer()).getByRole("link", { name: text(RU, "footer.source") });
    expect(link.getAttribute("href")).toBe(REPO_URL);
  });
});

/**
 * AC7 runtime check — no hard-coded UI strings.
 *
 * Every visible text node and every user-facing attribute in the rendered app
 * must come from the current locale. The only allowed literals are the
 * language codes on the switcher buttons (`EN`, `UK`, `RU`), fixed by the
 * contract. A hard-coded English string shows up as text that is not in the
 * Ukrainian or Russian locale.
 */
describe("AC7 — no hard-coded UI strings", () => {
  const USER_FACING_ATTRIBUTES = ["aria-label", "title", "alt", "placeholder"] as const;

  function collectUiStrings(root: HTMLElement): string[] {
    const found: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const value = node.textContent?.trim() ?? "";
      if (value !== "") {
        found.push(value);
      }
    }
    for (const element of Array.from(root.querySelectorAll("*"))) {
      for (const attribute of USER_FACING_ATTRIBUTES) {
        const value = element.getAttribute(attribute)?.trim() ?? "";
        if (value !== "") {
          found.push(value);
        }
      }
    }
    return found;
  }

  function untranslated(locale: FlatLocale): string[] {
    const values = allStrings(locale);
    const allowed = new Set<string>(LANG_BUTTONS);
    return collectUiStrings(document.body).filter(
      (s) => !allowed.has(s) && !values.some((v) => v.includes(s)),
    );
  }

  it("test_all_ui_strings_come_from_en_locale", async () => {
    await renderApp();
    expect(untranslated(EN)).toEqual([]);
  });

  it("test_all_ui_strings_come_from_uk_locale_after_switch", async () => {
    await renderApp();
    await switchTo("UK", EN, UK);
    expect(untranslated(UK)).toEqual([]);
  });

  it("test_all_ui_strings_come_from_ru_locale_after_switch", async () => {
    await renderApp();
    await switchTo("RU", EN, RU);
    expect(untranslated(RU)).toEqual([]);
  });
});

describe("T1 — no raw HTML in the rendered shell", () => {
  it("test_rendered_shell_contains_no_script_or_iframe_elements", async () => {
    await renderApp();
    expect(document.body.querySelectorAll("script, iframe, object, embed").length).toBe(0);
  });
});
