/** A slow count that started before "delete all" must not overwrite the state afterwards. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { setupI18n } from "../i18n";
import { resetBrowserEnv } from "../test/browser-env";
import { freshFactory } from "../test/idb-helpers";

const control = vi.hoisted(() => ({
  pending: null as Promise<number> | null,
}));

vi.mock("../storage/historySetting", async (importOriginal) => {
  const real = await importOriginal<typeof import("../storage/historySetting")>();
  return {
    ...real,
    countSavedResults: () => {
      const slow = control.pending;
      control.pending = null;
      return slow ?? real.countSavedResults();
    },
  };
});

afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
});

describe("settings panel race", () => {
  it("test_late_count_after_delete_all_does_not_restore_old_count", async () => {
    vi.stubGlobal("indexedDB", freshFactory());
    localStorage.setItem("aic.history", "on");
    let release: (n: number) => void = () => undefined;
    control.pending = new Promise<number>((resolve) => {
      release = resolve;
    });
    await setupI18n();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /data and history/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /delete all data in this browser/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog)
      .getAllByRole("button")
      .find((b) => !/cancel/i.test(b.textContent));
    if (!confirm) throw new Error("no confirm button");
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(screen.getByText("Saved results: 0")).toBeTruthy();
    });
    release(2);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("Saved results: 0")).toBeTruthy();
    expect(screen.queryByText("Saved results: 2")).toBeNull();
  });
});
