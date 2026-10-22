/**
 * S4-T2 AC9 — "Already analyzed" dialog.
 *
 * INJECTION POINTS: src/settings/CachedResultDialog.tsx exports
 *   CachedResultDialog(props: { savedAt: number epoch ms; onChoice(choice: "cached" | "new" | "cancel"): void })
 * The parent mounts it when needed and unmounts it after `onChoice`. Focus return to the
 * opener happens when the dialog unmounts (it remembers `document.activeElement` at mount).
 * Focus trap: handled in a keydown handler on Tab / Shift+Tab (jsdom does not move focus itself).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { I18nextProvider } from "react-i18next";
import i18next from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { changeLanguage, setupI18n } from "../i18n";
import { resetBrowserEnv } from "../test/browser-env";
import { CachedResultDialog } from "./CachedResultDialog";

const SAVED_AT = Date.UTC(2026, 2, 15, 12, 0, 0);

type Chooser = (c: "cached" | "new" | "cancel") => void;

function Harness({ onChoice }: { onChoice: Chooser }) {
  const [open, setOpen] = useState(false);
  return (
    <I18nextProvider i18n={i18next}>
      <button type="button" onClick={() => setOpen(true)}>
        opener
      </button>
      <button type="button">outside</button>
      {open ? (
        <CachedResultDialog
          savedAt={SAVED_AT}
          onChoice={(c) => {
            onChoice(c);
            setOpen(false);
          }}
        />
      ) : null}
    </I18nextProvider>
  );
}

async function openDialog(onChoice: Chooser = vi.fn()) {
  render(<Harness onChoice={onChoice} />);
  const opener = screen.getByRole("button", { name: "opener" });
  opener.focus();
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog");
  return { dialog, opener, onChoice };
}

const showBtn = () => screen.getByRole("button", { name: /show saved result/i });
const newBtn = () => screen.getByRole("button", { name: /run a new analysis/i });

beforeEach(async () => {
  localStorage.clear();
  await setupI18n();
  await changeLanguage("en");
});
afterEach(() => {
  resetBrowserEnv();
});

describe("CachedResultDialog (AC9)", () => {
  it("test_dialog_has_modal_role_and_is_labelled_by_its_heading", async () => {
    const { dialog } = await openDialog();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const id = dialog.getAttribute("aria-labelledby") ?? "";
    expect(id).not.toBe("");
    const heading = document.getElementById(id);
    expect(heading?.textContent.trim()).not.toBe("");
    expect(heading?.tagName).toMatch(/^H[1-6]$/);
  });

  it("test_dialog_shows_saved_date_formatted_for_en_ui", async () => {
    const { dialog } = await openDialog();
    expect(dialog.textContent).toMatch(/2026/);
    expect(dialog.textContent).toMatch(/Mar/);
  });

  it("test_dialog_shows_saved_date_formatted_for_uk_ui", async () => {
    await changeLanguage("uk");
    const { dialog } = await openDialog();
    expect(dialog.textContent).toMatch(/2026/);
    expect(dialog.textContent).toMatch(/бер/i);
  });

  it("test_dialog_shows_saved_date_formatted_for_ru_ui", async () => {
    await changeLanguage("ru");
    const { dialog } = await openDialog();
    expect(dialog.textContent).toMatch(/2026/);
    expect(dialog.textContent).toMatch(/мар/i);
  });

  it("test_focus_moves_to_first_button_on_open", async () => {
    await openDialog();
    expect(document.activeElement).toBe(showBtn());
  });

  it("test_tab_on_last_button_wraps_focus_to_first", async () => {
    await openDialog();
    newBtn().focus();
    fireEvent.keyDown(newBtn(), { key: "Tab" });
    expect(document.activeElement).toBe(showBtn());
  });

  it("test_shift_tab_on_first_button_wraps_focus_to_last", async () => {
    await openDialog();
    showBtn().focus();
    fireEvent.keyDown(showBtn(), { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(newBtn());
  });

  it("test_focus_leaving_the_dialog_is_pulled_back_inside", async () => {
    const { dialog } = await openDialog();
    screen.getByRole("button", { name: "outside" }).focus();
    await vi.waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("test_escape_reports_cancel_once", async () => {
    const { onChoice } = await openDialog();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(onChoice).toHaveBeenCalledTimes(1);
    expect(onChoice).toHaveBeenCalledWith("cancel");
  });

  it("test_show_saved_result_button_reports_cached", async () => {
    const { onChoice } = await openDialog();
    fireEvent.click(showBtn());
    expect(onChoice).toHaveBeenCalledWith("cached");
  });

  it("test_run_new_analysis_button_reports_new", async () => {
    const { onChoice } = await openDialog();
    fireEvent.click(newBtn());
    expect(onChoice).toHaveBeenCalledWith("new");
  });

  it("test_focus_returns_to_opener_after_escape", async () => {
    const { opener } = await openDialog();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(document.activeElement).toBe(opener);
  });

  it("test_focus_returns_to_opener_after_choice", async () => {
    const { opener } = await openDialog();
    fireEvent.click(newBtn());
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(document.activeElement).toBe(opener);
  });
});
