/**
 * S4-T2 AC8 — settings panel, reached from the page header through the App.
 *
 * INJECTION POINTS: none beyond the globals. Each test stubs the global `indexedDB`
 * with a fresh fake `IDBFactory` and uses jsdom `localStorage`. The panel is rendered by
 * `App` (src/App.tsx) behind a header button named "Data and history" (English UI).
 * Assumptions the developer must follow:
 *   - toggle: role="switch" named "Save results in this browser", `aria-checked`;
 *     unavailable state: `disabled` attribute or aria-disabled="true";
 *   - saved-results count is plain text containing the number (e.g. "Saved results: 2");
 *   - confirmations are in-page (NOT window.confirm): an element with role "dialog" or
 *     "alertdialog" holding the message and exactly two buttons: "Cancel" and a confirm button;
 *   - delete-all button name: "Delete all data in this browser".
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndexedDbCacheStore } from "../storage/indexedDbCacheStore";
import { freshFactory, openBlockingConnection, DB_NAME, databaseNames } from "../test/idb-helpers";
import { resetBrowserEnv } from "../test/browser-env";

const key = (n: number): string => n.toString(16).padStart(64, "0");

async function seed(factory: IDBFactory, count: number): Promise<void> {
  const store = new IndexedDbCacheStore({
    factory,
    clock: () => Date.now(),
    storage: { getItem: () => "on" },
  });
  for (let i = 0; i < count; i++) {
    await store.put(key(i), "analysis", { v: i });
  }
}

async function renderApp(): Promise<void> {
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("../App");
  const App = mod.default;
  render(<App />);
  await screen.findByRole("main");
}

async function openPanel(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: /data and history/i }));
  await screen.findByRole("switch", { name: /save results in this browser/i });
}

const theSwitch = () => screen.getByRole("switch", { name: /save results in this browser/i });

async function findConfirm(): Promise<HTMLElement> {
  const dialogs = await waitFor(() => {
    const found = [...screen.queryAllByRole("dialog"), ...screen.queryAllByRole("alertdialog")];
    if (found.length === 0) throw new Error("no confirmation dialog");
    return found;
  });
  const last = dialogs[dialogs.length - 1];
  if (!last) throw new Error("no dialog");
  return last;
}

function confirmButton(dialog: HTMLElement): HTMLElement {
  const buttons = within(dialog).getAllByRole("button");
  expect(buttons.length).toBe(2);
  const other = buttons.find((b) => !/cancel/i.test(b.textContent));
  if (!other) throw new Error("no confirm button");
  return other;
}

const cancelButton = (d: HTMLElement) => within(d).getByRole("button", { name: /cancel/i });
// The footer text ("AGPL-3.0 license") also contains digits, so ignore the footer.
const count = (n: number): HTMLElement => {
  const found = screen
    .getAllByText(new RegExp(`(^|\\D)${n}(\\D|$)`))
    .filter((el) => el.closest("footer") === null);
  const first = found[0];
  if (!first) throw new Error(`no count line with ${n}`);
  return first;
};

let factory: IDBFactory;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  factory = freshFactory();
  vi.stubGlobal("indexedDB", factory);
});
afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("settings panel (AC8)", () => {
  it("test_header_has_data_and_history_button_that_opens_the_panel", async () => {
    await renderApp();
    await openPanel();
    expect(theSwitch()).toBeTruthy();
  });

  it("test_toggle_is_a_switch_and_off_by_default", async () => {
    await renderApp();
    await openPanel();
    expect(theSwitch().getAttribute("aria-checked")).toBe("false");
  });

  it("test_panel_explains_90_days_not_encrypted_and_shared_computer", async () => {
    await renderApp();
    await openPanel();
    expect(screen.getByText(/90 days/i)).toBeTruthy();
    expect(screen.getByText(/not encrypted/i)).toBeTruthy();
    expect(screen.getByText(/shared computer/i)).toBeTruthy();
  });

  it("test_turning_on_stores_history_on_and_sets_aria_checked_true", async () => {
    await renderApp();
    await openPanel();
    fireEvent.click(theSwitch());
    await waitFor(() => {
      expect(theSwitch().getAttribute("aria-checked")).toBe("true");
    });
    expect(localStorage.getItem("aic.history")).toBe("on");
  });

  it("test_switch_reads_initial_on_state_and_shows_saved_count", async () => {
    localStorage.setItem("aic.history", "on");
    await seed(factory, 2);
    await renderApp();
    await openPanel();
    expect(theSwitch().getAttribute("aria-checked")).toBe("true");
    await waitFor(() => {
      expect(count(2)).toBeTruthy();
    });
  });

  it("test_turning_off_with_entries_asks_confirmation_and_cancel_keeps_history_on", async () => {
    localStorage.setItem("aic.history", "on");
    await seed(factory, 2);
    await renderApp();
    await openPanel();
    await waitFor(() => {
      expect(count(2)).toBeTruthy();
    });
    fireEvent.click(theSwitch());
    const dialog = await findConfirm();
    expect(within(dialog).getByText(/saved results will be deleted/i)).toBeTruthy();
    expect(localStorage.getItem("aic.history")).toBe("on");
    fireEvent.click(cancelButton(dialog));
    await waitFor(() => {
      expect(screen.queryByText(/saved results will be deleted/i)).toBeNull();
    });
    expect(theSwitch().getAttribute("aria-checked")).toBe("true");
    expect(localStorage.getItem("aic.history")).toBe("on");
    expect(await databaseNames(factory)).toContain(DB_NAME);
  });

  it("test_turning_off_with_entries_confirmed_deletes_entries_and_turns_off", async () => {
    localStorage.setItem("aic.history", "on");
    await seed(factory, 2);
    await renderApp();
    await openPanel();
    await waitFor(() => {
      expect(count(2)).toBeTruthy();
    });
    fireEvent.click(theSwitch());
    fireEvent.click(confirmButton(await findConfirm()));
    await waitFor(() => {
      expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    });
    expect(localStorage.getItem("aic.history")).toBeNull();
    await waitFor(async () => {
      expect(await databaseNames(factory)).not.toContain(DB_NAME);
    });
  });

  it("test_turning_off_without_entries_needs_no_confirmation", async () => {
    localStorage.setItem("aic.history", "on");
    await renderApp();
    await openPanel();
    fireEvent.click(theSwitch());
    await waitFor(() => {
      expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    });
    expect(screen.queryByText(/saved results will be deleted/i)).toBeNull();
    expect(localStorage.getItem("aic.history")).toBeNull();
  });

  it("test_unavailable_indexeddb_shows_message_and_disables_toggle", async () => {
    vi.stubGlobal("indexedDB", null);
    await renderApp();
    await openPanel();
    expect(screen.getByText(/history is not available in this browser/i)).toBeTruthy();
    const sw = theSwitch();
    const disabled =
      (sw as HTMLButtonElement).disabled || sw.getAttribute("aria-disabled") === "true";
    expect(disabled).toBe(true);
  });

  it("test_delete_all_asks_confirmation_and_cancel_changes_nothing", async () => {
    localStorage.setItem("aic.history", "on");
    await seed(factory, 1);
    await renderApp();
    await openPanel();
    fireEvent.click(screen.getByRole("button", { name: /delete all data in this browser/i }));
    const dialog = await findConfirm();
    fireEvent.click(cancelButton(dialog));
    await waitFor(() => {
      expect(
        screen.queryAllByRole("dialog").length + screen.queryAllByRole("alertdialog").length,
      ).toBe(0);
    });
    expect(localStorage.getItem("aic.history")).toBe("on");
    expect(await databaseNames(factory)).toContain(DB_NAME);
  });

  it("test_delete_all_confirmed_clears_data_toggle_off_and_count_zero", async () => {
    localStorage.setItem("aic.history", "on");
    localStorage.setItem("aic.lang", "en");
    sessionStorage.setItem("aic.x", "1");
    await seed(factory, 2);
    await renderApp();
    await openPanel();
    fireEvent.click(screen.getByRole("button", { name: /delete all data in this browser/i }));
    fireEvent.click(confirmButton(await findConfirm()));
    await waitFor(() => {
      expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    });
    await waitFor(() => {
      expect(count(0)).toBeTruthy();
    });
    expect(localStorage.getItem("aic.history")).toBeNull();
    expect(localStorage.getItem("aic.lang")).toBe("en");
    expect(sessionStorage.getItem("aic.x")).toBeNull();
    expect(await databaseNames(factory)).not.toContain(DB_NAME);
  });

  it("test_delete_all_blocked_by_other_tab_asks_to_close_other_tabs", async () => {
    localStorage.setItem("aic.history", "on");
    await renderApp();
    await openPanel();
    const other = await openBlockingConnection(factory, DB_NAME);
    try {
      fireEvent.click(screen.getByRole("button", { name: /delete all data in this browser/i }));
      fireEvent.click(confirmButton(await findConfirm()));
      expect(await screen.findByText(/close (the )?other tabs/i)).toBeTruthy();
    } finally {
      other.close();
    }
  });
});
