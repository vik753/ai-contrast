/**
 * Unit tests (frontend-dev): the `languageChanged` listener that keeps
 * `<html lang>` in sync is registered once per i18next instance, even when
 * this module is loaded and set up several times.
 */
import i18next from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetBrowserEnv } from "../test/browser-env";

type I18nModule = typeof import("./index");

async function freshModule(): Promise<I18nModule> {
  vi.resetModules();
  return import("./index");
}

/** Counts writes to `<html lang>` (a duplicate listener writes twice). */
async function countLangWrites(action: () => Promise<unknown>): Promise<number> {
  let writes = 0;
  const observer = new MutationObserver((records) => {
    writes += records.length;
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  await action();
  writes += observer.takeRecords().length;
  observer.disconnect();
  return writes;
}

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  resetBrowserEnv();
});

describe("html lang listener", () => {
  it("writes <html lang> once per direct change after repeated setup", async () => {
    for (let i = 0; i < 3; i += 1) {
      const { setupI18n } = await freshModule();
      await setupI18n();
    }
    const { default: instance } = await import("i18next");
    const writes = await countLangWrites(() => instance.changeLanguage("ru"));
    expect(writes).toBe(1);
    expect(document.documentElement.lang).toBe("ru");
  });

  it("maps an unsupported language to en", async () => {
    const { setupI18n } = await freshModule();
    const instance = await setupI18n();
    await instance.changeLanguage("de");
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("setupFallbackI18n", () => {
  it("switches to English and ignores the stored language", async () => {
    localStorage.setItem("aic.lang", "uk");
    const { setupI18n, setupFallbackI18n } = await freshModule();
    await setupI18n();
    const instance = await setupFallbackI18n();
    expect(instance.language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("never rejects, even if i18next fails", async () => {
    const { setupFallbackI18n } = await freshModule();
    vi.spyOn(i18next, "changeLanguage").mockRejectedValue(new Error("boom"));
    vi.spyOn(i18next, "init").mockRejectedValue(new Error("boom"));
    await expect(setupFallbackI18n()).resolves.toBeDefined();
    expect(document.documentElement.lang).toBe("en");
  });
});
