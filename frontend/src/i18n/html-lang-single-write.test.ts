/**
 * S1-T2c AC3 — `changeLanguage()` no longer sets `<html lang>` itself; the
 * `languageChanged` listener does. Result: one switch writes `<html lang>`
 * exactly once.
 *
 * Writes are counted with a MutationObserver: setting the attribute records a
 * mutation even when the value does not change, so a second writer shows up.
 * The file has one setup per test file run to keep i18next listeners clean.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resetBrowserEnv } from "../test/browser-env";

async function countLangWrites(action: () => Promise<unknown>): Promise<number> {
  let writes = 0;
  const observer = new MutationObserver((records) => {
    writes += records.length;
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  await action();
  await Promise.resolve();
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

describe("changeLanguage writes <html lang> once (S1-T2c AC3)", () => {
  it("test_change_language_uk_then_ru_writes_html_lang_once_each", async () => {
    const { setupI18n, changeLanguage } = await import("./index");
    await setupI18n();

    expect(await countLangWrites(() => changeLanguage("uk"))).toBe(1);
    expect(document.documentElement.lang).toBe("uk");

    expect(await countLangWrites(() => changeLanguage("ru"))).toBe(1);
    expect(document.documentElement.lang).toBe("ru");
  });
});
