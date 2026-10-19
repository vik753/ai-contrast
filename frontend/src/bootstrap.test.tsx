/**
 * S1-T2b AC8 — resilient start. Seam defined by test-engineer:
 *
 *   // src/bootstrap.ts or src/bootstrap.tsx
 *   export function start(
 *     container: Element,
 *     setup?: () => Promise<unknown>, // default: setupI18n
 *   ): Promise<Root>;                  // Root from "react-dom/client"
 *
 * `start` runs `setup`, then renders <App /> into `container`. If `setup`
 * rejects, `start` still resolves and the app renders in English.
 * `main.tsx` only finds `#root` and calls `start(container)`.
 *
 * The rejecting-setup case lives in `bootstrap-fallback.test.tsx`, so it runs
 * in a file where i18next was never initialized.
 */
import { screen } from "@testing-library/react";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enJson from "./i18n/locales/en.json";
import { resetBrowserEnv } from "./test/browser-env";
import { flattenLocale, text } from "./test/locale-utils";

const EN = flattenLocale(enJson);

let container: HTMLElement | undefined;
let root: Root | undefined;

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  root?.unmount();
  root = undefined;
  container?.remove();
  container = undefined;
  resetBrowserEnv();
});

function newContainer(id?: string): HTMLElement {
  const element = document.createElement("div");
  if (id !== undefined) {
    element.id = id;
  }
  document.body.append(element);
  container = element;
  return element;
}

describe("start() seam (S1-T2b AC8)", () => {
  it("test_start_with_default_setup_renders_english_app", async () => {
    vi.resetModules();
    const { start } = await import("./bootstrap");
    root = await start(newContainer());
    expect(await screen.findByText(text(EN, "home.tagline"))).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
  });

  it("test_start_runs_injected_setup_before_render", async () => {
    vi.resetModules();
    const { setupI18n } = await import("./i18n/index");
    const { start } = await import("./bootstrap");
    const setup = vi.fn(() => setupI18n());
    root = await start(newContainer(), setup);
    expect(setup).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("main")).toBeTruthy();
  });

  it("test_main_renders_app_into_root_element", async () => {
    newContainer("root");
    vi.resetModules();
    await import("./main");
    expect(await screen.findByText(text(EN, "home.tagline"))).toBeTruthy();
  });
});
