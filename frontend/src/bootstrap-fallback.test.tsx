/**
 * S1-T2b AC8 — if i18n setup rejects, the app still renders in English.
 *
 * Seam contract: see `bootstrap.test.tsx` (`start(container, setup?)`).
 * This file holds only the rejecting case, so i18next has not been
 * initialized by an earlier test in the same file.
 */
import { screen } from "@testing-library/react";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import enJson from "./i18n/locales/en.json";
import { resetBrowserEnv } from "./test/browser-env";
import { flattenLocale, text } from "./test/locale-utils";

const EN = flattenLocale(enJson);

let container: HTMLElement | undefined;
let root: Root | undefined;

afterEach(() => {
  root?.unmount();
  container?.remove();
  resetBrowserEnv();
});

describe("start() when setup rejects (S1-T2b AC8)", () => {
  it("test_start_with_rejecting_setup_resolves_and_renders_english", async () => {
    resetBrowserEnv();
    const { start } = await import("./bootstrap");
    container = document.createElement("div");
    document.body.append(container);

    root = await start(container, () => Promise.reject(new Error("synthetic setup failure")));

    expect(await screen.findByText(text(EN, "home.tagline"))).toBeTruthy();
    expect(screen.getByRole("link", { name: text(EN, "footer.source") })).toBeTruthy();
    expect(screen.getByText(text(EN, "footer.privacy"))).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
  });
});
