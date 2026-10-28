/** S4-T2 review fixes: history on but unreadable shows "not available" and disables the switch. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { freshFactory } from "../test/idb-helpers";
import { resetBrowserEnv } from "../test/browser-env";

afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
});

describe("settings panel review fixes", () => {
  it("test_history_on_but_store_cannot_open_shows_unavailable_and_disables_switch", async () => {
    const real = freshFactory();
    vi.stubGlobal(
      "indexedDB",
      new Proxy(real, {
        get(target, prop) {
          if (prop === "open") {
            return () => {
              throw new DOMException("denied", "SecurityError");
            };
          }
          const value = Reflect.get(target, prop, target) as unknown;
          return typeof value === "function" ? (value.bind(target) as unknown) : value;
        },
      }),
    );
    localStorage.setItem("aic.history", "on");
    vi.resetModules();
    const i18n = await import("../i18n/index");
    await i18n.setupI18n();
    const mod: { default: ComponentType } = await import("../App");
    const App = mod.default;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /data and history/i }));
    await screen.findByText(/history is not available in this browser/i);
    await waitFor(() => {
      const sw = screen.getByRole("switch", { name: /save results in this browser/i });
      expect((sw as HTMLButtonElement).disabled).toBe(true);
    });
  });
});
