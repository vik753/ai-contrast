/**
 * S3-T6b items 1–6 — Google Docs link in the upload form (src/upload/UploadForm.tsx).
 * Threats: T1 (plain text only), T7 (the ID is a password: memory only).
 *
 * Assumptions for the developer (same style as UploadForm.test.tsx):
 * - each contract `<section>` (role region "Contract A") has a text input
 *   labelled "Google Docs link" and a button whose accessible name is exactly
 *   "Add"; the hint text is rendered in the region;
 * - the inline error ("not a Google Docs document link", "already added") is
 *   plain text inside the region; no request is made for it, and no row;
 * - a Google document is an `<li>` row whose text contains
 *   "Google Docs document …<last 6 chars of the ID>", with a "Remove" button
 *   and the same status labels as an uploaded file ("Word document" once accepted);
 * - errors are shown in the row with the `upload.errors.<code>` text;
 * - a Google row beyond the file limits is a rejected row with the
 *   `too_many_files` message, and no request is made;
 * - requests go through the global `fetch` (stubbed here) to
 *   `/api/extract/google-doc`.
 *
 * These tests fail until the feature exists.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import {
  FakeFetch,
  acceptAsPdf,
  busyResponse,
  fileList,
  jsonResponse,
  makeFile,
  okResponse,
} from "../test/upload-fakes";
import { routeFetch } from "../test/segment-router";
import * as UploadFormModule from "./UploadForm";

const EN = flattenLocale(enJson);
const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;

const URL_PATH = "/api/extract/google-doc";
const ID_A = "DocIdAAAAAAAAAAAAAAAAAAAAabc123";
const ID_B = "DocIdBBBBBBBBBBBBBBBBBBBBBxyz789";
const ID_C = "DocIdCCCCCCCCCCCCCCCCCCCCCqrs456";
const linkOf = (id: string, tail = "/edit?usp=sharing"): string =>
  `https://docs.google.com/document/d/${id}${tail}`;
const nameOf = (id: string): string => `Google Docs document …${id.slice(-6)}`;

let server: FakeFetch;

beforeEach(() => {
  resetBrowserEnv();
  server = new FakeFetch();
  routeFetch(server);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

function field(label: string): HTMLInputElement {
  return within(region(label)).getByLabelText("Google Docs link");
}

function addButton(label: string): HTMLElement {
  return within(region(label)).getByRole("button", { name: "Add" });
}

function addLink(label: string, link: string): void {
  fireEvent.change(field(label), { target: { value: link } });
  fireEvent.click(addButton(label));
}

function addFiles(label: string, ...files: File[]): void {
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error("No file input");
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList(files) } });
  });
}

function row(label: string, text: string): HTMLElement {
  const item = within(region(label))
    .queryAllByRole("listitem")
    .find((li) => li.textContent.includes(text));
  if (item === undefined) {
    throw new Error(`No row containing ${text}`);
  }
  return item;
}

function rowOrNull(label: string, text: string): HTMLElement | null {
  return (
    within(region(label))
      .queryAllByRole("listitem")
      .find((li) => li.textContent.includes(text)) ?? null
  );
}

function docCalls() {
  return server.calls.filter((c) => c.input === URL_PATH);
}

function docBody(index: number): unknown {
  const body = docCalls()[index]?.body;
  return typeof body === "string" ? (JSON.parse(body) as unknown) : body;
}

function messagesFor(code: string): string[] {
  return Object.entries(EN)
    .filter(([key]) => key.split(".").includes(code))
    .map(([, value]) => String(value));
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const docx = (): Response => okResponse("docx", 4096);

describe("field, hint and link check (items 1, 2, 5)", () => {
  it("test_each_contract_has_a_google_docs_field_and_add_button", async () => {
    await renderForm();
    for (const label of ["A", "B"]) {
      expect(field(label).tagName).toBe("INPUT");
      expect(addButton(label).tagName).toBe("BUTTON");
    }
  });

  it("test_hint_about_anyone_with_the_link_is_shown_in_the_contract", async () => {
    await renderForm();
    expect(
      within(region("A")).getByText(
        "Share the document as “Anyone with the link can view”. For a private document, download it as DOCX or PDF and upload the file.",
      ),
    ).toBeTruthy();
  });

  it("test_field_has_autocomplete_off", async () => {
    await renderForm();
    expect(field("A").getAttribute("autocomplete")).toBe("off");
  });

  it("test_add_button_is_type_button", async () => {
    await renderForm();
    expect(addButton("A").getAttribute("type")).toBe("button");
  });

  it.each([
    ["other host", "https://docs.google.com.evil.com/document/d/" + ID_A + "/edit"],
    ["http scheme", "http://docs.google.com/document/d/" + ID_A + "/edit"],
    ["published form", "https://docs.google.com/document/d/e/2PACX-" + "a".repeat(40) + "/pub"],
    ["plain text", "my contract"],
  ])("test_invalid_link_%s_shows_error_and_sends_nothing", async (_name, link) => {
    await renderForm();
    addLink("A", link);
    expect(within(region("A")).getByText("This is not a Google Docs document link.")).toBeTruthy();
    expect(server.fetch).not.toHaveBeenCalled();
    expect(within(region("A")).queryByText(/Google Docs document …/)).toBeNull();
  });

  it("test_invalid_link_error_belongs_to_that_contract_only", async () => {
    await renderForm();
    addLink("A", "nope");
    expect(within(region("B")).queryByText("This is not a Google Docs document link.")).toBeNull();
  });

  it("test_markup_in_the_field_creates_no_element_and_is_not_a_link", async () => {
    await renderForm();
    addLink("A", '<img src=x onerror="alert(1)"><script>alert(1)</script>[x](javascript:alert(1))');
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(within(region("A")).queryAllByRole("link")).toHaveLength(0);
    expect(server.fetch).not.toHaveBeenCalled();
  });

  it("test_valid_link_with_padding_is_trimmed_and_sent", async () => {
    await renderForm();
    addLink("A", `  ${linkOf(ID_A)}\n`);
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    expect(docBody(0)).toEqual({ document_id: ID_A });
  });

  it.each(["/edit", "/view", "/preview", "/copy", "/", ""])(
    "test_valid_link_suffix_%j_is_sent_with_only_the_id",
    async (tail) => {
      await renderForm();
      addLink("A", linkOf(ID_A, tail));
      await waitFor(() => expect(docCalls()).toHaveLength(1));
      expect(docBody(0)).toEqual({ document_id: ID_A });
    },
  );
});

describe("request and row (items 3, 4)", () => {
  it("test_add_sends_post_json_with_omit_credentials_and_no_id_in_the_url", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    const call = docCalls()[0];
    expect(call?.input).toBe(URL_PATH);
    expect(call?.init?.method).toBe("POST");
    expect(call?.init?.credentials).toBe("omit");
    expect(call?.init?.redirect).toBe("error");
    expect(call?.init?.cache).toBe("no-store");
    expect(new Headers(call?.init?.headers).get("Content-Type")).toBe("application/json");
    expect(docBody(0)).toEqual({ document_id: ID_A });
  });

  it("test_add_shows_a_row_with_the_last_six_id_characters_while_waiting", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    expect(row("A", nameOf(ID_A))).toBeTruthy();
    expect(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i })).toBeTruthy();
  });

  it("test_row_label_is_in_the_contract_where_it_was_added", async () => {
    await renderForm();
    addLink("B", linkOf(ID_A));
    expect(rowOrNull("B", nameOf(ID_A))).not.toBeNull();
    expect(rowOrNull("A", nameOf(ID_A))).toBeNull();
  });

  it("test_accepted_google_doc_shows_word_document_like_an_upload", async () => {
    await renderForm();
    server.autoRespond = docx;
    addLink("A", linkOf(ID_A));
    await waitFor(() =>
      expect(within(row("A", nameOf(ID_A))).getByText("Word document")).toBeTruthy(),
    );
  });

  it("test_field_is_cleared_after_add", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    expect(field("A").value).toBe("");
  });

  it("test_full_id_and_pasted_link_are_not_rendered_anywhere", async () => {
    await renderForm();
    server.autoRespond = docx;
    addLink("A", linkOf(ID_A));
    await waitFor(() =>
      expect(within(row("A", nameOf(ID_A))).getByText("Word document")).toBeTruthy(),
    );
    expect(document.body.textContent).not.toContain(ID_A);
    expect(document.body.textContent).not.toContain("docs.google.com");
    expect(document.body.innerHTML).not.toContain(ID_A);
  });

  it("test_no_anchor_to_google_is_rendered", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    const anchors = Array.from(document.querySelectorAll("a"));
    expect(anchors.filter((a) => (a.getAttribute("href") ?? "").includes("google"))).toEqual([]);
    expect(within(region("A")).queryAllByRole("link")).toHaveLength(0);
  });

  it("test_two_different_ids_make_two_rows_and_two_requests", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    addLink("A", linkOf(ID_B));
    await waitFor(() => expect(docCalls()).toHaveLength(2));
    expect(rowOrNull("A", nameOf(ID_A))).not.toBeNull();
    expect(rowOrNull("A", nameOf(ID_B))).not.toBeNull();
  });
});

describe("error codes shown in the row (item 6)", () => {
  const CODES: readonly (readonly [string, number])[] = [
    ["invalid_request", 422],
    ["invalid_google_doc_id", 422],
    ["google_doc_not_public", 422],
    ["google_doc_not_found", 422],
    ["google_doc_too_large", 422],
    ["google_doc_unavailable", 502],
    ["google_doc_timeout", 504],
    ["request_too_large", 413],
    ["unsupported_media_type", 415],
    ["extraction_failed", 422],
    ["extraction_timeout", 422],
    ["too_many_pages", 422],
    ["too_much_text", 422],
    ["encrypted_unsupported", 422],
    ["no_text_extracted", 422],
    ["suspicious_package", 422],
    ["archive_rejected", 422],
    ["docx_strict_unsupported", 422],
  ];

  it.each(CODES)("test_code_%s_status_%i_is_shown_in_the_row", async (code, status) => {
    await renderForm();
    server.autoRespond = () => jsonResponse(status, { error: code });
    addLink("A", linkOf(ID_A));
    const messages = messagesFor(code);
    expect(messages.length).toBeGreaterThan(0);
    await waitFor(() => {
      const text = row("A", nameOf(ID_A)).textContent;
      expect(messages.some((m) => text.includes(m.replace(/\{\{\w+\}\}/g, "")))).toBe(true);
    });
    expect(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i })).toBeTruthy();
  });

  it("test_network_failure_is_shown_in_the_row", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    act(() => docCalls()[0]?.fail(new TypeError("Failed to fetch")));
    const messages = messagesFor("network_error");
    await waitFor(() =>
      expect(messages.some((m) => row("A", nameOf(ID_A)).textContent.includes(m))).toBe(true),
    );
  });

  it("test_unknown_code_is_not_shown_and_server_text_never_appears", async () => {
    await renderForm();
    server.autoRespond = () => jsonResponse(422, { error: "SERVER-TEXT-CANARY" });
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    await waitFor(() =>
      expect(
        messagesFor("unknown_error").some((m) => row("A", nameOf(ID_A)).textContent.includes(m)),
      ).toBe(true),
    );
    expect(document.body.textContent).not.toContain("SERVER-TEXT-CANARY");
  });

  it("test_error_row_does_not_show_the_full_id", async () => {
    await renderForm();
    server.autoRespond = () => jsonResponse(422, { error: "google_doc_not_public" });
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(row("A", nameOf(ID_A)).textContent).not.toContain("Checking"));
    expect(document.body.textContent).not.toContain(ID_A);
  });
});

describe("duplicates (item 4)", () => {
  it("test_same_id_in_same_contract_is_refused_with_message_and_no_request", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    addLink("A", linkOf(ID_A));
    expect(within(region("A")).getByText("This document is already added.")).toBeTruthy();
    expect(docCalls()).toHaveLength(1);
    expect(
      within(region("A"))
        .queryAllByRole("listitem")
        .filter((li) => li.textContent.includes(nameOf(ID_A))),
    ).toHaveLength(1);
  });

  it("test_same_id_in_another_link_form_is_still_a_duplicate", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A, "/edit"));
    addLink("A", linkOf(ID_A, "/view#heading=h.x"));
    expect(within(region("A")).getByText("This document is already added.")).toBeTruthy();
    expect(docCalls()).toHaveLength(1);
  });

  it("test_duplicate_is_refused_after_the_first_one_was_accepted", async () => {
    await renderForm();
    server.autoRespond = docx;
    addLink("A", linkOf(ID_A));
    await waitFor(() =>
      expect(within(row("A", nameOf(ID_A))).getByText("Word document")).toBeTruthy(),
    );
    addLink("A", linkOf(ID_A));
    expect(within(region("A")).getByText("This document is already added.")).toBeTruthy();
    expect(docCalls()).toHaveLength(1);
  });

  it("test_same_id_in_another_contract_is_allowed", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    addLink("B", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(2));
    expect(within(region("B")).queryByText("This document is already added.")).toBeNull();
  });

  it("test_same_id_can_be_added_again_after_the_row_was_removed", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    fireEvent.click(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i }));
    addLink("A", linkOf(ID_A));
    expect(within(region("A")).queryByText("This document is already added.")).toBeNull();
    await waitFor(() => expect(docCalls()).toHaveLength(2));
  });
});

describe("removal aborts (item 4)", () => {
  it("test_removing_google_row_aborts_its_request_and_removes_the_row", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    fireEvent.click(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i }));
    expect(docCalls()[0]?.signal?.aborted).toBe(true);
    expect(rowOrNull("A", nameOf(ID_A))).toBeNull();
  });

  it("test_removed_google_row_does_not_reappear_after_the_aborted_answer", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    fireEvent.click(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i }));
    await act(async () => {
      docCalls()[0]?.respond(docx());
      await Promise.resolve();
    });
    expect(rowOrNull("A", nameOf(ID_A))).toBeNull();
  });

  it("test_removing_the_contract_aborts_its_google_request", async () => {
    await renderForm();
    fireEvent.click(screen.getByRole("button", { name: "Add contract" }));
    addLink("C", linkOf(ID_A));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
    fireEvent.click(within(region("C")).getByRole("button", { name: /remove.*contract c\b/i }));
    expect(docCalls()[0]?.signal?.aborted).toBe(true);
  });

  it("test_removing_google_row_frees_its_slot_for_a_queued_file", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    addLink("A", linkOf(ID_B));
    addFiles("B", makeFile("queued.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    fireEvent.click(within(row("A", nameOf(ID_A))).getByRole("button", { name: /remove/i }));
    await waitFor(() => expect(server.calls).toHaveLength(3));
  });
});

describe("scheduler and limits (item 4)", () => {
  it("test_google_docs_and_uploads_share_two_request_slots", async () => {
    await renderForm();
    addLink("A", linkOf(ID_A));
    addLink("A", linkOf(ID_B));
    addFiles("B", makeFile("a.pdf"), makeFile("b.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    await act(async () => {
      await Promise.resolve();
    });
    expect(server.pending()).toHaveLength(2);
    expect(server.calls).toHaveLength(2);
  });

  it("test_queued_google_doc_starts_when_a_slot_frees", async () => {
    await renderForm();
    addFiles("A", makeFile("a.pdf"), makeFile("b.pdf"));
    addLink("B", linkOf(ID_A));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    expect(docCalls()).toHaveLength(0);
    act(() => server.calls[0]?.respond(acceptAsPdf(server.calls[0].body)));
    await waitFor(() => expect(docCalls()).toHaveLength(1));
  });

  it("test_busy_google_request_is_retried_with_the_same_body_after_retry_after", async () => {
    await renderForm();
    vi.useFakeTimers();
    addLink("A", linkOf(ID_A));
    await flush();
    expect(docCalls()).toHaveLength(1);
    act(() => docCalls()[0]?.respond(busyResponse("5")));
    await flush(4_999);
    expect(docCalls()).toHaveLength(1);
    await flush(1);
    expect(docCalls()).toHaveLength(2);
    expect(docBody(1)).toEqual({ document_id: ID_A });
  });

  it("test_busy_retry_delay_for_google_request_is_capped_at_10_seconds", async () => {
    await renderForm();
    vi.useFakeTimers();
    addLink("A", linkOf(ID_A));
    await flush();
    act(() => docCalls()[0]?.respond(busyResponse("999")));
    await flush(10_000);
    expect(docCalls()).toHaveLength(2);
  });

  it("test_google_request_times_out_after_60_seconds", async () => {
    await renderForm();
    vi.useFakeTimers();
    addLink("A", linkOf(ID_A));
    await flush();
    await flush(59_999);
    expect(docCalls()[0]?.signal?.aborted).toBe(false);
    await flush(1);
    expect(docCalls()[0]?.signal?.aborted).toBe(true);
  });

  it("test_google_document_counts_toward_the_five_files_per_contract", async () => {
    await renderForm();
    addFiles("A", makeFile("1.pdf"), makeFile("2.pdf"), makeFile("3.pdf"), makeFile("4.pdf"));
    addLink("A", linkOf(ID_A));
    addFiles("A", makeFile("6.pdf"));
    const messages = messagesFor("too_many_files");
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.some((m) => row("A", "6.pdf").textContent.includes(m))).toBe(true);
    expect(rowOrNull("A", nameOf(ID_A))).not.toBeNull();
  });

  it("test_google_document_over_the_file_limit_is_rejected_without_a_request", async () => {
    await renderForm();
    addFiles(
      "A",
      makeFile("1.pdf"),
      makeFile("2.pdf"),
      makeFile("3.pdf"),
      makeFile("4.pdf"),
      makeFile("5.pdf"),
    );
    await waitFor(() => expect(server.calls).toHaveLength(2));
    addLink("A", linkOf(ID_A));
    const messages = messagesFor("too_many_files");
    expect(messages.some((m) => row("A", nameOf(ID_A)).textContent.includes(m))).toBe(true);
    expect(docCalls()).toHaveLength(0);
    server.autoRespond = acceptAsPdf;
    server.pending().forEach((c) => c.respond(acceptAsPdf(c.body)));
    await act(async () => {
      await Promise.resolve();
    });
    expect(docCalls()).toHaveLength(0);
  });
});

describe("the ID stays in memory (item 5, T7)", () => {
  async function runFlow(): Promise<void> {
    await renderForm();
    server.autoRespond = (body) =>
      typeof body === "string" ? jsonResponse(200, okBody()) : acceptAsPdf(body);
    addLink("A", linkOf(ID_A));
    addLink("A", linkOf(ID_B));
    await waitFor(() =>
      expect(within(row("A", nameOf(ID_A))).getByText("Word document")).toBeTruthy(),
    );
    fireEvent.click(within(row("A", nameOf(ID_B))).getByRole("button", { name: /remove/i }));
    addLink("A", linkOf(ID_C));
    await waitFor(() => expect(docCalls().length).toBeGreaterThanOrEqual(3));
  }

  function okBody(): Record<string, unknown> {
    return {
      kind: "docx",
      bytes: 4096,
      language: "en",
      pages: null,
      blocks: [{ text: "Clause.", part: "body", page: null }],
      ocr_pages: [],
      removed: [],
      warnings: [],
    };
  }

  function mentions(value: unknown, id: string): boolean {
    try {
      return JSON.stringify(value).includes(id);
    } catch {
      return String(value).includes(id);
    }
  }

  it("test_no_storage_write_contains_an_id", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await runFlow();
    for (const call of setItem.mock.calls) {
      for (const id of [ID_A, ID_B, ID_C]) {
        expect(mentions(call, id)).toBe(false);
      }
    }
    for (const store of [localStorage, sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i) ?? "";
        for (const id of [ID_A, ID_B, ID_C]) {
          expect(key.includes(id) || (store.getItem(key) ?? "").includes(id)).toBe(false);
        }
      }
    }
  });

  it("test_session_storage_is_not_written_at_all", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await runFlow();
    expect(sessionStorage.length).toBe(0);
    expect(setItem.mock.contexts.filter((ctx) => ctx === sessionStorage)).toHaveLength(0);
  });

  it("test_indexeddb_is_never_opened", async () => {
    const open = vi.fn();
    vi.stubGlobal("indexedDB", { open, deleteDatabase: vi.fn() });
    await runFlow();
    expect(open).not.toHaveBeenCalled();
  });

  it("test_console_output_never_contains_an_id", async () => {
    const spies = (["log", "info", "warn", "error", "debug", "trace"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    await runFlow();
    for (const spy of spies) {
      for (const call of spy.mock.calls) {
        for (const id of [ID_A, ID_B, ID_C]) {
          expect(mentions(call, id)).toBe(false);
        }
      }
    }
  });

  it("test_location_and_history_never_contain_an_id", async () => {
    await runFlow();
    for (const id of [ID_A, ID_B, ID_C]) {
      expect(document.location.href).not.toContain(id);
      expect(mentions(window.history.state, id)).toBe(false);
    }
    expect(document.location.hash).toBe("");
    expect(document.location.search).toBe("");
  });

  it("test_id_is_only_in_the_request_body_never_in_url_or_headers", async () => {
    await runFlow();
    for (const call of docCalls()) {
      expect(String(call.input)).not.toContain(ID_A);
      expect(mentions(Array.from(new Headers(call.init?.headers).entries()), ID_A)).toBe(false);
    }
  });
});
