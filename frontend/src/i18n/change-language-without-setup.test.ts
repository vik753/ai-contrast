/**
 * PR #3 review follow-up 6 — `changeLanguage()` updates `<html lang>` even
 * when `setupI18n()` was never called in this module instance.
 *
 * Own test file, so i18next was not set up by an earlier test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetBrowserEnv } from "../test/browser-env";

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  resetBrowserEnv();
});

describe("changeLanguage without setupI18n (PR #3 follow-up 6)", () => {
  it("test_change_language_without_setup_updates_html_lang", async () => {
    vi.resetModules();
    const { changeLanguage } = await import("./index");
    await changeLanguage("uk");
    expect(document.documentElement.lang).toBe("uk");
  });
});
