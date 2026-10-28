/**
 * S4-T1 AC4, AC5, AC7, AC8 — file hash and text hash through the upload form.
 *
 * Assumptions (same style as UploadForm.test.tsx and googleDoc.form.test.tsx):
 * - a refused duplicate is a rejected `<li>` row showing the `duplicate_file`
 *   message (key path segment `duplicate_file`), no request is made;
 * - warnings are plain text inside the `<li>` row of the new row (the row that
 *   is added, or that becomes accepted last); the English copy is the one
 *   quoted in the task, `{{…}}` is the contract label;
 * - while the file hash is computed the row shows "Waiting" (status `queued`).
 * Everything is synthetic; `fetch` is a fake; hashes are computed with Node's
 * crypto in the test.
 */
import { createHash } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import { FakeFetch, fileList, keyContaining, makeFile, okResponse } from "../test/upload-fakes";
import { routeFetch } from "../test/segment-router";
import * as UploadFormModule from "./UploadForm";

const EN = flattenLocale(enJson);
const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;

const GOOGLE_URL = "/api/extract/google-doc";
const ID_A = "DocIdAAAAAAAAAAAAAAAAAAAAabc123";
const nameOf = (id: string): string => `Google Docs document …${id.slice(-6)}`;
const linkOf = (id: string): string => `https://docs.google.com/document/d/${id}/edit`;

const sha = (text: string): string => createHash("sha256").update(text, "utf8").digest("hex");

/** English copy with every `{{…}}` placeholder replaced by `label`. */
function copy(phrase: string, label: string): string {
  let value: string;
  try {
    value = String(EN[keyContaining(EN, phrase)]);
  } catch {
    return `<<missing locale value: ${phrase}>>`;
  }
  return value.replace(/\{\{\s*\w+\s*\}\}/g, label);
}
const SAME_FILE_IN = (label: string): string => copy("The same file is in Contract", label);
const SAME_TEXT_HERE = copy("Same text as another file in this contract", "");
const SAME_TEXT_IN = (label: string): string => copy("Same text as a file in Contract", label);
const DUPLICATE_FILE = Object.entries(EN)
  .filter(([key]) => key.split(".").includes("duplicate_file"))
  .map(([, value]) => String(value));

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

const region = (label: string): HTMLElement =>
  screen.getByRole("region", { name: `Contract ${label}` });

function addFiles(label: string, ...files: File[]): void {
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error("No file input");
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList(files) } });
  });
}

function addLink(label: string, id: string): void {
  fireEvent.change(within(region(label)).getByLabelText("Google Docs link"), {
    target: { value: linkOf(id) },
  });
  fireEvent.click(within(region(label)).getByRole("button", { name: "Add" }));
}

function rowOrNull(label: string, name: string): HTMLElement | null {
  return (
    within(region(label))
      .queryAllByRole("listitem")
      .find((li) => li.textContent.includes(name)) ?? null
  );
}

function row(label: string, name: string): HTMLElement {
  const item = rowOrNull(label, name);
  if (item === null) {
    throw new Error(`No row containing ${name} in Contract ${label}`);
  }
  return item;
}

function rowText(label: string, name: string): string {
  return rowOrNull(label, name)?.textContent ?? "";
}

/** Every answer of the fake server is a DOCX with the next text of `texts`. */
function answerWithTexts(...texts: (string | string[])[]): void {
  let index = 0;
  server.autoRespond = (body) => {
    const entry = texts[Math.min(index, texts.length - 1)] ?? "";
    index += 1;
    const parts = Array.isArray(entry) ? entry : [entry];
    return okResponse("docx", body instanceof Blob ? body.size : 4096, {
      blocks: parts.map((text) => ({ text, part: "body", page: null })),
    });
  };
}

async function waitAccepted(label: string, name: string): Promise<void> {
  await waitFor(() => {
    expect(rowText(label, name)).toContain("Word document");
  });
}

const settle = (ms = 60): Promise<void> =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

describe("AC4 — file hash before upload", () => {
  it("test_same_bytes_in_same_contract_second_row_is_refused_as_duplicate_file", async () => {
    await renderForm();
    answerWithTexts("one");
    addFiles("A", makeFile("first.docx", { content: "SAME BYTES" }));
    await waitAccepted("A", "first.docx");
    addFiles("A", makeFile("copy.docx", { content: "SAME BYTES" }));
    await waitFor(() => {
      expect(DUPLICATE_FILE.some((m) => rowText("A", "copy.docx").includes(m))).toBe(true);
    });
  });

  it("test_same_bytes_in_same_contract_sends_no_request_for_the_second_row", async () => {
    await renderForm();
    answerWithTexts("one");
    addFiles("A", makeFile("first.docx", { content: "SAME BYTES" }));
    await waitAccepted("A", "first.docx");
    addFiles("A", makeFile("copy.docx", { content: "SAME BYTES" }));
    await waitFor(() => {
      expect(DUPLICATE_FILE.some((m) => rowText("A", "copy.docx").includes(m))).toBe(true);
    });
    await settle();
    expect(server.calls).toHaveLength(1);
  });

  it("test_same_bytes_in_one_batch_second_row_is_refused_with_one_request", async () => {
    await renderForm();
    answerWithTexts("one");
    addFiles(
      "A",
      makeFile("one.docx", { content: "SAME BYTES" }),
      makeFile("two.docx", { content: "SAME BYTES" }),
    );
    await waitFor(() => {
      expect(DUPLICATE_FILE.some((m) => rowText("A", "two.docx").includes(m))).toBe(true);
    });
    await settle();
    expect(server.calls).toHaveLength(1);
  });

  it("test_same_bytes_with_a_different_name_is_still_a_duplicate", async () => {
    await renderForm();
    answerWithTexts("one");
    addFiles("A", makeFile("a.docx", { content: "SAME BYTES" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("renamed.txt", { content: "SAME BYTES", type: "text/plain" }));
    await waitFor(() => {
      expect(DUPLICATE_FILE.some((m) => rowText("A", "renamed.txt").includes(m))).toBe(true);
    });
  });

  it("test_different_bytes_in_same_contract_are_not_a_duplicate", async () => {
    await renderForm();
    answerWithTexts("one", "two");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    expect(DUPLICATE_FILE.some((m) => rowText("A", "b.docx").includes(m))).toBe(false);
    expect(server.calls).toHaveLength(2);
  });

  it("test_same_bytes_as_a_rejected_row_is_not_a_duplicate", async () => {
    await renderForm();
    answerWithTexts("one");
    addFiles("A", makeFile("notes.pages", { content: "SAME BYTES" }));
    expect(server.calls).toHaveLength(0);
    addFiles("A", makeFile("good.docx", { content: "SAME BYTES" }));
    await waitAccepted("A", "good.docx");
    expect(DUPLICATE_FILE.some((m) => rowText("A", "good.docx").includes(m))).toBe(false);
  });

  it("test_same_bytes_in_another_contract_is_accepted_with_a_warning_naming_the_contract", async () => {
    await renderForm();
    answerWithTexts("one", "two");
    addFiles("A", makeFile("a.docx", { content: "SAME BYTES" }));
    await waitAccepted("A", "a.docx");
    addFiles("B", makeFile("b.docx", { content: "SAME BYTES" }));
    await waitAccepted("B", "b.docx");
    expect(rowText("B", "b.docx")).toContain(SAME_FILE_IN("A"));
    expect(DUPLICATE_FILE.some((m) => rowText("B", "b.docx").includes(m))).toBe(false);
    expect(server.calls).toHaveLength(2);
  });

  it("test_different_bytes_in_another_contract_show_no_same_file_warning", async () => {
    await renderForm();
    answerWithTexts("one", "two");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("B", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("B", "b.docx");
    expect(rowText("B", "b.docx")).not.toContain(SAME_FILE_IN("A"));
  });
});

describe("AC5 — text hash after extraction", () => {
  it("test_same_text_in_same_contract_shows_a_warning_and_both_rows_stay_accepted", async () => {
    await renderForm();
    answerWithTexts("The parties agree.", "The parties agree.");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    await waitFor(() => {
      expect(rowText("A", "b.docx")).toContain(SAME_TEXT_HERE);
    });
    expect(rowText("A", "a.docx")).toContain("Word document");
  });

  it("test_same_text_in_another_contract_shows_a_warning_naming_the_contract", async () => {
    await renderForm();
    answerWithTexts("The parties agree.", "The parties agree.");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("B", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("B", "b.docx");
    await waitFor(() => {
      expect(rowText("B", "b.docx")).toContain(SAME_TEXT_IN("A"));
    });
    expect(rowText("B", "b.docx")).not.toContain(SAME_TEXT_HERE);
  });

  it("test_different_text_shows_no_text_warning", async () => {
    await renderForm();
    answerWithTexts("The parties agree.", "The parties disagree.");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    await settle();
    expect(rowText("A", "b.docx")).not.toContain(SAME_TEXT_HERE);
    expect(rowText("A", "b.docx")).not.toContain(SAME_TEXT_IN("A"));
  });

  it("test_text_differing_only_in_white_space_counts_as_the_same_text", async () => {
    await renderForm();
    answerWithTexts("Line one\nLine  two", "  Line one\r\nLine\ttwo  \n\n\n");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    await waitFor(() => {
      expect(rowText("A", "b.docx")).toContain(SAME_TEXT_HERE);
    });
  });

  it("test_text_blocks_are_joined_with_a_blank_line_before_hashing", async () => {
    await renderForm();
    answerWithTexts(["First block", "Second block"], "First block\n\nSecond block");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    await waitFor(() => {
      expect(rowText("A", "b.docx")).toContain(SAME_TEXT_HERE);
    });
  });

  it("test_same_blocks_in_a_different_order_are_a_different_text", async () => {
    await renderForm();
    answerWithTexts(["First block", "Second block"], ["Second block", "First block"]);
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addFiles("A", makeFile("b.docx", { content: "BYTES TWO" }));
    await waitAccepted("A", "b.docx");
    await settle();
    expect(rowText("A", "b.docx")).not.toContain(SAME_TEXT_HERE);
  });

  it("test_google_row_with_the_same_text_as_an_uploaded_file_shows_a_warning", async () => {
    await renderForm();
    answerWithTexts("The parties agree.", "The parties agree.");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addLink("A", ID_A);
    await waitAccepted("A", nameOf(ID_A));
    await waitFor(() => {
      expect(rowText("A", nameOf(ID_A))).toContain(SAME_TEXT_HERE);
    });
    expect(server.calls.some((c) => c.input === GOOGLE_URL)).toBe(true);
  });

  it("test_google_row_with_the_same_text_in_another_contract_names_the_contract", async () => {
    await renderForm();
    answerWithTexts("The parties agree.", "The parties agree.");
    addFiles("A", makeFile("a.docx", { content: "BYTES ONE" }));
    await waitAccepted("A", "a.docx");
    addLink("B", ID_A);
    await waitAccepted("B", nameOf(ID_A));
    await waitFor(() => {
      expect(rowText("B", nameOf(ID_A))).toContain(SAME_TEXT_IN("A"));
    });
  });
});

describe("AC7 — hashes stay in memory and never leave the browser", () => {
  const FILE_A = "BYTES ONE";
  const FILE_B = "BYTES TWO";
  const TEXT = "The parties agree.";

  function spyEverything() {
    return {
      setItem: vi.spyOn(Storage.prototype, "setItem"),
      open: vi.fn(),
      logs: (["log", "info", "debug", "warn", "error"] as const).map((m) =>
        vi.spyOn(console, m).mockImplementation(() => undefined),
      ),
    };
  }

  it("test_hashing_is_done_with_crypto_subtle_digest", async () => {
    await renderForm();
    const digest = vi.spyOn(crypto.subtle, "digest");
    answerWithTexts(TEXT);
    addFiles("A", makeFile("a.docx", { content: FILE_A }));
    await waitAccepted("A", "a.docx");
    // File hash and text hash; the text hash waits for the clause split (S5-T2).
    await waitFor(() => {
      expect(digest.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    for (const call of digest.mock.calls) {
      expect(call[0]).toBe("SHA-256");
    }
  });

  it("test_hashes_are_not_written_to_any_storage", async () => {
    await renderForm();
    const spies = spyEverything();
    vi.stubGlobal("indexedDB", { open: spies.open });
    answerWithTexts(TEXT, TEXT);
    addFiles("A", makeFile("a.docx", { content: FILE_A }));
    await waitAccepted("A", "a.docx");
    addFiles("B", makeFile("b.docx", { content: FILE_B }));
    await waitAccepted("B", "b.docx");
    addFiles("B", makeFile("c.docx", { content: FILE_A }));
    await settle();
    expect(spies.setItem).not.toHaveBeenCalled();
    expect(spies.open).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("test_hashes_are_not_in_the_page_url_console_or_announcements", async () => {
    await renderForm();
    const spies = spyEverything();
    answerWithTexts(TEXT, TEXT);
    addFiles("A", makeFile("a.docx", { content: FILE_A }));
    await waitAccepted("A", "a.docx");
    addFiles("B", makeFile("b.docx", { content: FILE_A }));
    await waitAccepted("B", "b.docx");
    await settle();
    const hashes = [sha(FILE_A), sha(TEXT)];
    const logged = JSON.stringify(spies.logs.flatMap((s) => s.mock.calls.map(String)));
    for (const hash of hashes) {
      for (const prefix of [hash, hash.slice(0, 16)]) {
        expect(document.body.innerHTML).not.toContain(prefix);
        expect(window.location.href).not.toContain(prefix);
        expect(logged).not.toContain(prefix);
      }
    }
  });

  it("test_no_hash_is_sent_in_any_request", async () => {
    await renderForm();
    answerWithTexts(TEXT, TEXT);
    addFiles("A", makeFile("a.docx", { content: FILE_A }));
    await waitAccepted("A", "a.docx");
    addLink("A", ID_A);
    await waitAccepted("A", nameOf(ID_A));
    expect(server.calls.length).toBeGreaterThanOrEqual(2);
    const hashes = [sha(FILE_A), sha(TEXT)];
    for (const call of server.calls) {
      const sent = JSON.stringify({
        url: String(call.input),
        headers: call.init?.headers ?? null,
        body: typeof call.body === "string" ? call.body : null,
      });
      for (const hash of hashes) {
        expect(sent).not.toContain(hash);
        expect(sent).not.toContain(hash.slice(0, 16));
      }
      expect(sent).not.toMatch(/[0-9a-f]{64}/);
      // A file is still sent as the file itself, not wrapped with extra data.
      if (typeof call.body !== "string") {
        expect(call.body).toBeInstanceOf(Blob);
      }
    }
  });
});

const FILE_BYTES = "SOME BYTES";

describe("AC8 — asynchronous hash, queued until done, removal drops the result", () => {
  function gateDigest() {
    const real = crypto.subtle.digest.bind(crypto.subtle);
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const spy = vi.spyOn(crypto.subtle, "digest").mockImplementation(async (algorithm, data) => {
      await gate;
      return real(algorithm, data);
    });
    return { spy, release };
  }

  it("test_row_stays_queued_and_sends_no_request_until_the_hash_is_done", async () => {
    await renderForm();
    const { spy, release } = gateDigest();
    answerWithTexts("one");
    addFiles("A", makeFile("a.docx", { content: FILE_BYTES }));
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    expect(rowText("A", "a.docx")).toContain("Waiting");
    expect(server.calls).toHaveLength(0);
    release();
    await waitAccepted("A", "a.docx");
    expect(server.calls).toHaveLength(1);
  });

  it("test_removing_a_row_while_hashing_sends_no_request_and_drops_the_result", async () => {
    await renderForm();
    const { spy, release } = gateDigest();
    answerWithTexts("one");
    addFiles("A", makeFile("a.docx", { content: FILE_BYTES }));
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    fireEvent.click(within(row("A", "a.docx")).getByRole("button", { name: /remove/i }));
    expect(rowOrNull("A", "a.docx")).toBeNull();
    release();
    await settle();
    expect(server.calls).toHaveLength(0);
    expect(rowOrNull("A", "a.docx")).toBeNull();
  });

  it("test_same_bytes_added_again_after_removal_during_hashing_are_not_a_duplicate", async () => {
    await renderForm();
    const { spy, release } = gateDigest();
    answerWithTexts("one");
    addFiles("A", makeFile("a.docx", { content: FILE_BYTES }));
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    fireEvent.click(within(row("A", "a.docx")).getByRole("button", { name: /remove/i }));
    release();
    await settle();
    addFiles("A", makeFile("again.docx", { content: FILE_BYTES }));
    await waitAccepted("A", "again.docx");
    expect(DUPLICATE_FILE.some((m) => rowText("A", "again.docx").includes(m))).toBe(false);
  });
});
