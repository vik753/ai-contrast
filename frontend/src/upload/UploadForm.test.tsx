/**
 * S2-T2 — the upload form (src/upload/UploadForm.tsx).
 * Covers AC1–AC10 and AC12 through the rendered component.
 * Threats: T1 (no HTML sinks, server text never shown), T3, T6, T11.
 *
 * The public interface gives the form no props, so the tests replace the
 * global `fetch` with a controllable fake (`vi.stubGlobal`). `extractFile`
 * must therefore read `globalThis.fetch` at call time.
 * The form is rendered inside `I18nextProvider` after `setupI18n()`, like App.
 *
 * Assumptions (see the report): each contract card is a `<section>` named by
 * its heading ("Contract A"); each file row is an `<li>` inside that section;
 * the per-file "Remove" button name matches /remove/i; the contract removal
 * button name contains "Remove" and the contract label.
 *
 * These tests fail until `src/upload/UploadForm.tsx` exists.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import ukJson from "../i18n/locales/uk.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale, type FlatLocale } from "../test/locale-utils";
import {
  FakeFetch,
  MIB,
  acceptAsPdf,
  busyResponse,
  canary,
  fileList,
  interpolate,
  jsonResponse,
  keyContaining,
  makeFile,
  okResponse,
  pluralBase,
  templateRegExp,
} from "../test/upload-fakes";
import { MAX_FILE_BYTES, MAX_FILES_PER_CONTRACT, MAX_TOTAL_BYTES } from "./limits";
import * as UploadFormModule from "./UploadForm";

const EN = flattenLocale(enJson);
const UK = flattenLocale(ukJson);

const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;

const READY_FOR_ANY = "Add at least one file to each contract";
const CHECKING_FILES = "Checking files…";
const WAITING = "Waiting";
const CHECKING = "Checking…";

let server: FakeFetch;

beforeEach(() => {
  resetBrowserEnv();
  server = new FakeFetch();
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

async function renderForm(): Promise<void> {
  await setupI18n();
  render(
    <I18nextProvider i18n={i18next}>
      <UploadForm />
    </I18nextProvider>,
  );
  await screen.findByRole("region", { name: "Contract A" });
}

function region(label: string): HTMLElement {
  return screen.getByRole("region", { name: `Contract ${label}` });
}

function addFilesButton(label: string): HTMLElement {
  return screen.getByRole("button", { name: `Add files to Contract ${label}` });
}

function fileInput(label: string): HTMLInputElement {
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error(`No file input in Contract ${label}`);
  }
  return input;
}

function addViaInput(label: string, ...files: File[]): void {
  act(() => {
    fireEvent.change(fileInput(label), { target: { files: fileList(files) } });
  });
}

function row(label: string, name: string): HTMLElement {
  const item = within(region(label))
    .getAllByText(name)
    .map((el) => el.closest("li"))
    .find((li): li is HTMLLIElement => li !== null);
  if (item === undefined) {
    throw new Error(`No <li> row for ${name} in Contract ${label}`);
  }
  return item;
}

function removeFileButton(label: string, name: string): HTMLElement {
  return within(row(label, name)).getByRole("button", { name: /remove/i });
}

function removeContractButton(label: string): HTMLElement | null {
  return within(region(label)).queryByRole("button", {
    name: new RegExp(`remove.*contract ${label}\\b`, "i"),
  });
}

function required(element: HTMLElement | null): HTMLElement {
  if (element === null) {
    throw new Error("Expected button is not rendered");
  }
  return element;
}

function addContractButton(): HTMLElement | null {
  return screen.queryByRole("button", { name: "Add contract" });
}

/** en locale values for an error code: keys with a path segment equal to the code. */
function messagesFor(code: string, locale: FlatLocale = EN): string[] {
  return Object.entries(locale)
    .filter(([key]) => key.split(".").includes(code))
    .map(([, value]) => String(value));
}

function expectRowShowsCode(rowEl: HTMLElement, code: string): void {
  const messages = messagesFor(code);
  expect(messages.length).toBeGreaterThan(0);
  const textContent = rowEl.textContent;
  expect(messages.some((m) => textContent.includes(m))).toBe(true);
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/**
 * Negative checks ("nothing else happens") run on fake timers: render with
 * real timers first (Testing Library's async helpers need them), then switch.
 * QUIET_MS is long but below the 60 s request timeout, so no request ends.
 */
const QUIET_MS = 30_000;

function startFakeClock(): void {
  vi.useFakeTimers();
}

describe("AC1 — contracts", () => {
  it("test_form_starts_with_contract_a_and_b", async () => {
    await renderForm();
    expect(region("A")).toBeTruthy();
    expect(region("B")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Contract C" })).toBeNull();
  });

  it("test_add_contract_adds_contract_c", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    expect(region("C")).toBeTruthy();
  });

  it("test_add_contract_stops_at_five", async () => {
    await renderForm();
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(required(addContractButton()));
    }
    expect(region("E")).toBeTruthy();
    const button = addContractButton();
    if (button !== null) {
      expect(
        button.hasAttribute("disabled") || button.getAttribute("aria-disabled") === "true",
      ).toBe(true);
      fireEvent.click(button);
    }
    expect(screen.queryByRole("region", { name: "Contract F" })).toBeNull();
    expect(screen.getAllByRole("region", { name: /^Contract [A-Z]$/ })).toHaveLength(5);
  });

  it("test_remove_contract_is_not_available_with_two_contracts", async () => {
    await renderForm();
    for (const label of ["A", "B"]) {
      const button = removeContractButton(label);
      if (button !== null) {
        expect(button.hasAttribute("disabled")).toBe(true);
      }
    }
  });

  it("test_remove_contract_is_available_with_three_contracts", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    const button = removeContractButton("C");
    expect(button).not.toBeNull();
    expect(button?.hasAttribute("disabled")).toBe(false);
  });

  it("test_removing_b_turns_c_into_b", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    addViaInput("C", makeFile("c-file.txt", { content: "plain text" }));
    fireEvent.click(required(removeContractButton("B")));
    expect(screen.queryByRole("region", { name: "Contract C" })).toBeNull();
    expect(within(region("B")).getByText("c-file.txt")).toBeTruthy();
  });
});

describe("AC2 — adding files", () => {
  it("test_add_files_button_is_a_real_button", async () => {
    await renderForm();
    const button = addFilesButton("A");
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("type")).toBe("button");
  });

  it("test_file_input_accepts_multiple_pdf_docx_txt", async () => {
    await renderForm();
    const input = fileInput("A");
    expect(input.multiple).toBe(true);
    expect(input.getAttribute("accept")).toBe(".pdf,.docx,.txt");
  });

  it("test_add_files_button_opens_that_contracts_file_picker", async () => {
    await renderForm();
    const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => undefined);
    fireEvent.click(addFilesButton("B"));
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.contexts[0]).toBe(fileInput("B"));
  });

  it("test_picked_files_appear_in_the_contract", async () => {
    await renderForm();
    addViaInput("A", makeFile("main.pdf"), makeFile("annex-1.pdf"));
    expect(row("A", "main.pdf")).toBeTruthy();
    expect(row("A", "annex-1.pdf")).toBeTruthy();
    expect(within(region("B")).queryByText("main.pdf")).toBeNull();
  });

  it("test_drop_on_contract_card_adds_files", async () => {
    await renderForm();
    const card = region("B");
    const dataTransfer = { files: fileList([makeFile("dropped.pdf")]), types: ["Files"] };
    act(() => {
      fireEvent.dragOver(card, { dataTransfer });
      fireEvent.drop(card, { dataTransfer });
    });
    expect(row("B", "dropped.pdf")).toBeTruthy();
  });

  it("test_drop_and_dragover_prevent_browser_default", async () => {
    await renderForm();
    const card = region("A");
    const dataTransfer = { files: fileList([makeFile("dropped.pdf")]), types: ["Files"] };
    let dragOverNotPrevented = true;
    let dropNotPrevented = true;
    act(() => {
      dragOverNotPrevented = fireEvent.dragOver(card, { dataTransfer });
      dropNotPrevented = fireEvent.drop(card, { dataTransfer });
    });
    expect(dragOverNotPrevented).toBe(false);
    expect(dropNotPrevented).toBe(false);
  });
});

describe("AC3 — client checks before any request", () => {
  it.each([
    ["big.pdf", { size: 10 * MIB + 1 }, "file_too_large"],
    ["empty.txt", { content: "" }, "empty_file"],
    ["report.pages", {}, "pages_unsupported"],
    ["old.doc", {}, "legacy_office_unsupported"],
  ] as const)("test_%s_is_rejected_without_request", async (name, options, code) => {
    await renderForm();
    startFakeClock();
    addViaInput("A", makeFile(name, options));
    await flush(QUIET_MS);
    expect(server.fetch).not.toHaveBeenCalled();
    const r = row("A", name);
    expectRowShowsCode(r, code);
    expect(within(r).getByRole("button", { name: /remove/i })).toBeTruthy();
  });

  it("test_sixth_file_is_rejected_too_many_files", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    const files = Array.from({ length: 6 }, (_, i) => makeFile(`part-${i}.pdf`));
    addViaInput("A", ...files);
    await waitFor(() => expect(server.fetch).toHaveBeenCalledTimes(5));
    expectRowShowsCode(row("A", "part-5.pdf"), "too_many_files");
  });

  it("test_file_over_total_limit_is_rejected_total_too_large", async () => {
    await renderForm();
    const big = Array.from({ length: 5 }, (_, i) => makeFile(`big-${i}.pdf`, { size: 10 * MIB }));
    addViaInput("A", ...big);
    addViaInput("B", makeFile("small.txt", { content: "x" }));
    expectRowShowsCode(row("B", "small.txt"), "total_too_large");
  });

  it("test_doc_shows_save_as_docx_or_pdf_message", async () => {
    await renderForm();
    addViaInput("A", makeFile("old.doc"));
    expect(row("A", "old.doc").textContent).toContain(
      "Save the file as .docx or PDF and try again",
    );
  });

  it("test_pages_shows_export_to_pdf_message", async () => {
    await renderForm();
    addViaInput("A", makeFile("report.pages"));
    expect(row("A", "report.pages").textContent).toContain("Export to PDF: File → Export To → PDF");
  });

  it("test_rejected_file_remove_button_removes_row", async () => {
    await renderForm();
    addViaInput("A", makeFile("old.doc"));
    fireEvent.click(removeFileButton("A", "old.doc"));
    expect(within(region("A")).queryByText("old.doc")).toBeNull();
  });
});

describe("AC4 — server check and queue", () => {
  it("test_valid_file_is_sent_and_shows_pdf", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("main.pdf"));
    await waitFor(() => expect(within(row("A", "main.pdf")).getByText("PDF")).toBeTruthy());
    expect(server.fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["docx", "Word document"],
    ["text", "Text file"],
  ] as const)("test_kind_%s_shows_label_%s", async (kind, label) => {
    await renderForm();
    server.autoRespond = (body) => okResponse(kind, (body as Blob).size);
    addViaInput("A", makeFile("doc.bin"));
    await waitFor(() => expect(within(row("A", "doc.bin")).getByText(label)).toBeTruthy());
  });

  it("test_at_most_two_requests_in_flight_rest_waiting", async () => {
    await renderForm();
    startFakeClock();
    const files = Array.from({ length: 4 }, (_, i) => makeFile(`f${i}.pdf`));
    addViaInput("A", ...files);
    await flush();
    expect(server.calls).toHaveLength(2);
    await flush(QUIET_MS);
    expect(server.calls).toHaveLength(2);
    const statuses = files.map((f) => row("A", f.name).textContent);
    expect(statuses.filter((t) => t.includes(CHECKING))).toHaveLength(2);
    expect(statuses.filter((t) => t.includes(WAITING))).toHaveLength(2);
  });

  it("test_limit_of_two_applies_to_the_whole_form", async () => {
    await renderForm();
    startFakeClock();
    addViaInput("A", makeFile("a1.pdf"), makeFile("a2.pdf"));
    addViaInput("B", makeFile("b1.pdf"), makeFile("b2.pdf"));
    await flush();
    expect(server.calls).toHaveLength(2);
    await flush(QUIET_MS);
    expect(server.calls).toHaveLength(2);
  });

  it("test_finished_request_starts_next_queued_file", async () => {
    await renderForm();
    const files = Array.from({ length: 3 }, (_, i) => makeFile(`f${i}.pdf`));
    addViaInput("A", ...files);
    await waitFor(() => expect(server.calls).toHaveLength(2));
    const first = server.calls[0];
    act(() => first?.respond(acceptAsPdf(first.body)));
    await waitFor(() => expect(server.calls).toHaveLength(3));
  });

  it("test_network_failure_shows_network_error", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(1));
    act(() => server.calls[0]?.fail(new TypeError("Failed to fetch")));
    await waitFor(() => expectRowShowsCode(row("A", "a.pdf"), "network_error"));
  });

  it("test_server_rejection_shows_reason", async () => {
    await renderForm();
    server.autoRespond = () => jsonResponse(422, { error: "unsupported_type" });
    addViaInput("A", makeFile("image.pdf"));
    await waitFor(() => expectRowShowsCode(row("A", "image.pdf"), "unsupported_type"));
  });

  it("test_server_text_is_never_shown", async () => {
    await renderForm();
    const secret = canary("SERVER-TEXT");
    server.autoRespond = () =>
      jsonResponse(422, { error: "unsupported_type", message: secret, detail: `<b>${secret}</b>` });
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expectRowShowsCode(row("A", "a.pdf"), "unsupported_type"));
    expect(document.body.textContent).not.toContain(secret);
  });

  it("test_unknown_server_code_is_not_shown", async () => {
    await renderForm();
    const secret = canary("SERVER-CODE");
    server.autoRespond = () => jsonResponse(422, { error: secret });
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expectRowShowsCode(row("A", "a.pdf"), "unknown_error"));
    expect(document.body.textContent).not.toContain(secret);
  });
});

describe("AC4 — busy retry and timeout (fake timers)", () => {
  async function startOne(): Promise<void> {
    // Render with real timers: Testing Library's async helpers wait on a real
    // setTimeout(0) and hang under fake timers. Timers created later are fake.
    await renderForm();
    vi.useFakeTimers();
    addViaInput("A", makeFile("a.pdf"));
    await flush();
    expect(server.calls).toHaveLength(1);
  }

  it("test_busy_is_retried_after_retry_after_seconds", async () => {
    await startOne();
    act(() => server.calls[0]?.respond(busyResponse("5")));
    await flush(4_999);
    expect(server.calls).toHaveLength(1);
    await flush(1);
    expect(server.calls).toHaveLength(2);
    const second = server.calls[1];
    act(() => second?.respond(acceptAsPdf(second.body)));
    await flush();
    expect(within(row("A", "a.pdf")).getByText("PDF")).toBeTruthy();
  });

  it("test_busy_retry_delay_is_capped_at_10_seconds", async () => {
    await startOne();
    act(() => server.calls[0]?.respond(busyResponse("120")));
    await flush(9_999);
    expect(server.calls).toHaveLength(1);
    await flush(1);
    expect(server.calls).toHaveLength(2);
  });

  it("test_busy_makes_at_most_three_attempts_in_total", async () => {
    await startOne();
    for (let attempt = 0; attempt < 3; attempt += 1) {
      act(() => server.calls[attempt]?.respond(busyResponse("1")));
      await flush(10_000);
    }
    await flush(60_000);
    expect(server.calls).toHaveLength(3);
    expectRowShowsCode(row("A", "a.pdf"), "busy");
  });

  it("test_retry_sends_the_same_file_body", async () => {
    await startOne();
    act(() => server.calls[0]?.respond(busyResponse("1")));
    await flush(1_000);
    expect(server.calls[1]?.body).toBe(server.calls[0]?.body);
  });

  it("test_request_times_out_after_60_seconds", async () => {
    await startOne();
    await flush(60_000);
    expectRowShowsCode(row("A", "a.pdf"), "timeout");
  });
});

describe("AC5 — request privacy through the form (T3, T11)", () => {
  it("test_request_has_no_file_name_and_raw_body", async () => {
    await renderForm();
    const marker = canary("FILENAME");
    const file = makeFile(`${marker}.pdf`, { type: "application/pdf" });
    addViaInput("A", file);
    await waitFor(() => expect(server.calls).toHaveLength(1));
    const call = server.calls[0];
    expect(call?.input).toBe("/api/extract");
    expect(call?.init?.method?.toUpperCase()).toBe("POST");
    expect(call?.body).toBe(file);
    const headers = Array.from(new Headers(call?.init?.headers).entries());
    expect(headers).toEqual([["content-type", "application/octet-stream"]]);
    expect(JSON.stringify(headers)).not.toContain(marker);
    expect(String(call?.input)).not.toContain(marker);
  });
});

describe("AC7 — file rows", () => {
  it("test_row_shows_file_name_as_plain_text", async () => {
    await renderForm();
    addViaInput("A", makeFile("Agreement 2026.pdf"));
    expect(within(row("A", "Agreement 2026.pdf")).getByText("Agreement 2026.pdf")).toBeTruthy();
  });

  it("test_row_shows_size_in_english_units", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf", { size: 2048 }));
    expect(row("A", "a.pdf").textContent).toMatch(/2(?:[.,]0+)?\s?[kK]i?B/);
  });

  it("test_row_shows_size_in_ukrainian_units_after_switch", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf", { size: 2048 }));
    await act(async () => {
      await i18next.changeLanguage("uk");
    });
    const rows = screen.getAllByText("a.pdf").map((el) => el.closest("li"));
    const text = rows.find((li) => li !== null)?.textContent ?? "";
    expect(text).toMatch(/2(?:[.,]0+)?\s?[кК]/);
  });

  it("test_waiting_and_checking_labels_are_shown", async () => {
    await renderForm();
    addViaInput("A", makeFile("f0.pdf"), makeFile("f1.pdf"), makeFile("f2.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    expect(within(row("A", "f0.pdf")).getByText(CHECKING)).toBeTruthy();
    expect(within(row("A", "f2.pdf")).getByText(WAITING)).toBeTruthy();
  });

  it("test_status_has_an_icon_next_to_the_text_label", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.doc"));
    await waitFor(() => expect(within(row("A", "a.pdf")).getByText("PDF")).toBeTruthy());
    for (const r of [row("A", "a.pdf"), row("B", "b.doc")]) {
      expect(r.querySelector('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it("test_one_polite_live_region", async () => {
    await renderForm();
    const live = document.querySelectorAll('[aria-live="polite"], [role="status"]');
    expect(live).toHaveLength(1);
    expect(live[0]?.getAttribute("aria-live") ?? "polite").toBe("polite");
  });

  it("test_status_change_is_announced_in_the_live_region", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    const live = document.querySelector('[aria-live="polite"]');
    const before = live?.textContent ?? "";
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expect(within(row("A", "a.pdf")).getByText("PDF")).toBeTruthy());
    await waitFor(() => {
      const now = document.querySelector('[aria-live="polite"]')?.textContent ?? "";
      expect(now.trim()).not.toBe("");
      expect(now).not.toBe(before);
    });
    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  });
});

describe("AC8 — removal aborts and moves focus", () => {
  it("test_removing_file_aborts_its_request", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(1));
    fireEvent.click(removeFileButton("A", "a.pdf"));
    expect(server.calls[0]?.signal?.aborted).toBe(true);
    expect(within(region("A")).queryByText("a.pdf")).toBeNull();
  });

  it("test_removing_file_frees_its_slot", async () => {
    await renderForm();
    addViaInput("A", makeFile("f0.pdf"), makeFile("f1.pdf"), makeFile("f2.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    fireEvent.click(removeFileButton("A", "f0.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(3));
  });

  it("test_removing_file_moves_focus_to_add_files_button", async () => {
    await renderForm();
    addViaInput("B", makeFile("a.pdf"));
    fireEvent.click(removeFileButton("B", "a.pdf"));
    await waitFor(() => expect(document.activeElement).toBe(addFilesButton("B")));
  });

  it("test_removing_contract_aborts_all_its_requests", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    addViaInput("C", makeFile("c1.pdf"), makeFile("c2.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    fireEvent.click(required(removeContractButton("C")));
    expect(server.calls.every((c) => c.signal?.aborted === true)).toBe(true);
  });

  it("test_aborted_file_does_not_reappear", async () => {
    await renderForm();
    startFakeClock();
    addViaInput("A", makeFile("a.pdf"));
    await flush();
    expect(server.calls).toHaveLength(1);
    fireEvent.click(removeFileButton("A", "a.pdf"));
    await flush(QUIET_MS);
    expect(screen.queryByText("a.pdf")).toBeNull();
  });
});

describe("AC9 — readiness line", () => {
  it("test_initial_readiness_asks_for_files", async () => {
    await renderForm();
    expect(screen.getByText(READY_FOR_ANY)).toBeTruthy();
  });

  it("test_readiness_shows_checking_while_requests_run", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"));
    await waitFor(() => expect(screen.getByText(CHECKING_FILES)).toBeTruthy());
  });

  it("test_readiness_shows_ready_with_count", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"));
    await waitFor(() => expect(screen.getByText("Ready to compare: 2 contracts")).toBeTruthy());
  });

  it("test_ready_uses_ukrainian_few_plural_for_two", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"));
    await waitFor(() => expect(screen.getByText("Ready to compare: 2 contracts")).toBeTruthy());
    const key = Object.keys(EN).find((k) =>
      templateRegExp(String(EN[k])).test("Ready to compare: 2 contracts"),
    );
    expect(key).toBeDefined();
    const fewKey = `${pluralBase(key ?? "")}_few`;
    await act(async () => {
      await i18next.changeLanguage("uk");
    });
    expect(screen.getByText(interpolate(String(UK[fewKey]), { count: 2 }))).toBeTruthy();
  });

  it("test_there_is_no_continue_button", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"));
    await waitFor(() => expect(screen.getByText("Ready to compare: 2 contracts")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /continue/i })).toBeNull();
  });
});

describe("AC10 — privacy note", () => {
  it("test_privacy_note_is_under_the_contracts", async () => {
    await renderForm();
    const note = screen.getByText(/not stored/i);
    expect(note.textContent).toMatch(/file names/i);
    const last = region("B");
    expect(last.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("AC12 — accessibility structure", () => {
  it.each(["A", "B"])("test_contract_%s_is_a_section_with_heading", async (label) => {
    await renderForm();
    const section = region(label);
    expect(section.tagName).toBe("SECTION");
    expect(within(section).getByRole("heading", { name: `Contract ${label}` })).toBeTruthy();
  });

  it("test_contract_heading_is_translated", async () => {
    await renderForm();
    await act(async () => {
      await i18next.changeLanguage("uk");
    });
    const key = Object.keys(EN).find(
      (k) => templateRegExp(String(EN[k])).test("Contract A") && !String(EN[k]).includes("Add"),
    );
    expect(key).toBeDefined();
    const ukTemplate = templateRegExp(String(UK[key ?? ""]));
    const headings = screen.getAllByRole("heading").map((h) => h.textContent.trim());
    expect(headings.some((h) => ukTemplate.test(h) && h.endsWith("A"))).toBe(true);
    expect(headings).not.toContain("Contract A");
  });

  it("test_every_button_has_type_button", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    addViaInput("A", makeFile("old.doc"));
    for (const button of screen.getAllByRole("button")) {
      expect(button.getAttribute("type")).toBe("button");
    }
  });
});

describe("T1 / T11 — file names render as plain text", () => {
  it("test_html_file_name_is_plain_text", async () => {
    await renderForm();
    const name = "<img src=x onerror=alert(1)>.pdf";
    addViaInput("A", makeFile(name));
    expect(row("A", name)).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("test_script_file_name_is_plain_text", async () => {
    await renderForm();
    const name = "<script>alert(1)</script>.txt";
    addViaInput("A", makeFile(name));
    expect(row("A", name)).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
  });

  it("test_markdown_link_file_name_is_not_a_link", async () => {
    await renderForm();
    const name = "[click](https://evil.example).txt";
    addViaInput("A", makeFile(name));
    expect(row("A", name)).toBeTruthy();
    expect(document.querySelector('a[href*="evil.example"]')).toBeNull();
  });
});

/* ------------------------------------------------------------------------ */
/* Review round 1 (PR #16)                                                  */
/* ------------------------------------------------------------------------ */

function liveRegion(): HTMLElement {
  const element = document.querySelector<HTMLElement>('[aria-live="polite"]');
  if (element === null) {
    throw new Error("No polite live region");
  }
  return element;
}

function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Finds the rendered message of `code` in `text` and returns the values that
 * stand in its `{{placeholders}}`. A value is a number with an optional unit.
 */
function placeholderValues(text: string, code: string): string[][] {
  const templates = messagesFor(code).filter((v) => /\{\{\s*\w+\s*\}\}/.test(v));
  const found: string[][] = [];
  for (const template of templates) {
    const pattern = template
      .trim()
      .split(/\{\{\s*\w+\s*\}\}/)
      .map(escapeForRegExp)
      .join("(\\d[\\d.,]*(?:\\s?[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+)?)");
    const match = new RegExp(pattern).exec(text);
    if (match !== null) {
      found.push(match.slice(1));
    }
  }
  return found;
}

function expectMessageLimit(rowEl: HTMLElement, code: string, limit: number): void {
  const found = placeholderValues(rowEl.textContent, code);
  expect(found.length).toBeGreaterThan(0);
  for (const values of found) {
    expect(values.some((v) => new RegExp(`(^|\\D)${limit}(\\D|$)`).test(v))).toBe(true);
  }
}

describe("Review round 1 — i18n options and untrusted file names (T1, T11)", () => {
  const TRICKY = "$t(upload.title) {{label}}";

  it("test_skip_on_variables_is_true", async () => {
    await setupI18n();
    expect(i18next.options.interpolation?.skipOnVariables).toBe(true);
  });

  it("test_escape_value_stays_false_because_react_escapes", async () => {
    await setupI18n();
    expect(i18next.options.interpolation?.escapeValue).toBe(false);
  });

  it("test_tricky_name_appears_word_for_word_in_the_row", async () => {
    await renderForm();
    addViaInput("A", makeFile(TRICKY));
    expect(row("A", TRICKY).textContent).toContain(TRICKY);
  });

  it("test_tricky_name_appears_word_for_word_in_the_remove_label", async () => {
    await renderForm();
    addViaInput("A", makeFile(TRICKY));
    const button = within(row("A", TRICKY)).getByRole("button", {
      name: (accessibleName) => accessibleName.includes(TRICKY),
    });
    expect(button).toBeTruthy();
  });

  it("test_tricky_name_appears_word_for_word_in_the_live_region", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile(TRICKY));
    await waitFor(() => expect(within(row("A", TRICKY)).getByText("PDF")).toBeTruthy());
    await waitFor(() => expect(liveRegion().textContent).toContain(TRICKY));
  });

  it("test_file_name_is_wrapped_in_bdi", async () => {
    await renderForm();
    const name = "договір-عقد-contract.pdf";
    addViaInput("A", makeFile(name));
    const bdis = Array.from(row("A", name).querySelectorAll("bdi"));
    expect(bdis.some((b) => b.textContent === name)).toBe(true);
  });
});

describe("Review round 1 — readiness reason rejected_files", () => {
  it("test_rejected_file_shows_remove_rejected_files_line", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"), makeFile("annex.doc"));
    const key = keyContaining(EN, "Remove the files that were not accepted");
    await waitFor(() => expect(screen.getByText(String(EN[key]))).toBeTruthy());
    expect(screen.queryByText("Ready to compare: 2 contracts")).toBeNull();
  });

  it("test_removing_rejected_file_makes_form_ready", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    addViaInput("B", makeFile("b.pdf"), makeFile("annex.doc"));
    await waitFor(() => expect(within(row("B", "b.pdf")).getByText("PDF")).toBeTruthy());
    fireEvent.click(removeFileButton("B", "annex.doc"));
    await waitFor(() => expect(screen.getByText("Ready to compare: 2 contracts")).toBeTruthy());
  });
});

describe("Review round 1 — focus after contract changes", () => {
  it("test_add_contract_moves_focus_to_new_add_files_button", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    await waitFor(() => expect(document.activeElement).toBe(addFilesButton("C")));
  });

  it("test_adding_fifth_contract_moves_focus_to_its_add_files_button", async () => {
    await renderForm();
    for (const label of ["C", "D", "E"]) {
      fireEvent.click(required(addContractButton()));
      await waitFor(() => expect(document.activeElement).toBe(addFilesButton(label)));
    }
  });

  it("test_removing_contract_moves_focus_to_add_contract", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    fireEvent.click(required(removeContractButton("C")));
    await waitFor(() => expect(document.activeElement).toBe(addContractButton()));
  });

  it("test_removing_middle_contract_moves_focus_to_add_contract", async () => {
    await renderForm();
    fireEvent.click(required(addContractButton()));
    fireEvent.click(required(addContractButton()));
    fireEvent.click(required(removeContractButton("B")));
    await waitFor(() => expect(document.activeElement).toBe(addContractButton()));
  });
});

describe("Review round 1 — live region and language change", () => {
  it("test_language_change_clears_old_announcements", async () => {
    await renderForm();
    server.autoRespond = acceptAsPdf;
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expect(within(row("A", "a.pdf")).getByText("PDF")).toBeTruthy());
    await waitFor(() => expect(liveRegion().textContent.trim()).not.toBe(""));
    const english = liveRegion().textContent;
    await act(async () => {
      await i18next.changeLanguage("uk");
    });
    const now = liveRegion().textContent;
    expect(now).not.toContain(english.trim());
    // Nothing from the English locale is left in the region.
    const englishValues = Object.values(EN)
      .map(
        (v) =>
          String(v)
            .split(/\{\{\s*\w+\s*\}\}/)[0]
            ?.trim() ?? "",
      )
      .filter((v) => v.length >= 6 && !Object.values(UK).includes(v));
    expect(englishValues.filter((v) => now.includes(v))).toEqual([]);
  });

  it("test_queued_to_checking_step_is_not_announced", async () => {
    await renderForm();
    addViaInput("A", makeFile("a.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(1));
    expect(liveRegion().textContent).not.toContain(CHECKING);
  });
});

describe("Review round 1 — sizes round up (1 MB = 1024² bytes)", () => {
  it("test_10485761_bytes_shows_10_1_mb", async () => {
    await renderForm();
    addViaInput("A", makeFile("big.pdf", { size: 10_485_761 }));
    const text = row("A", "big.pdf").textContent;
    expect(text).toMatch(/10\.1\s?MB/);
    expect(text).not.toMatch(/(^|[^\d.,])10\s?MB/);
  });

  it("test_1048575_bytes_shows_1_mb_not_1024_kb", async () => {
    // Expected: "1 MB" (rounded up; never a value below the real size and
    // never "1,024 KB").
    await renderForm();
    addViaInput("A", makeFile("almost.pdf", { size: 1_048_575 }));
    const text = row("A", "almost.pdf").textContent;
    expect(text).toMatch(/(^|[^\d.,])1(\.0)?\s?MB/);
    expect(text).not.toMatch(/1,?024\s?KB/);
  });

  it("test_1025_bytes_shows_1_1_kb", async () => {
    await renderForm();
    addViaInput("A", makeFile("small.pdf", { size: 1025 }));
    expect(row("A", "small.pdf").textContent).toMatch(/1\.1\s?KB/);
  });
});

describe("Review round 1 — limits in messages come from limits.ts", () => {
  it("test_file_too_large_message_shows_10", async () => {
    await renderForm();
    addViaInput("A", makeFile("big.pdf", { size: MAX_FILE_BYTES + 1 }));
    expectMessageLimit(row("A", "big.pdf"), "file_too_large", MAX_FILE_BYTES / MIB);
  });

  it("test_too_many_files_message_shows_5", async () => {
    await renderForm();
    startFakeClock();
    const files = Array.from({ length: 6 }, (_, i) => makeFile(`part-${i}.pdf`));
    addViaInput("A", ...files);
    await flush();
    expectMessageLimit(row("A", "part-5.pdf"), "too_many_files", MAX_FILES_PER_CONTRACT);
  });

  it("test_total_too_large_message_shows_50", async () => {
    await renderForm();
    startFakeClock();
    const big = Array.from({ length: 5 }, (_, i) => makeFile(`big-${i}.pdf`, { size: 10 * MIB }));
    addViaInput("A", ...big);
    addViaInput("B", makeFile("small.txt", { content: "x" }));
    await flush();
    expectMessageLimit(row("B", "small.txt"), "total_too_large", MAX_TOTAL_BYTES / MIB);
  });
});
