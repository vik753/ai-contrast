/**
 * S3-T4 AC2–AC5 — the Preview section per contract, driven through
 * `UploadForm` with a fake global `fetch` that returns stage 3 bodies.
 * Threats: T1 (no HTML sinks, raw server codes never shown), T3, T5.
 *
 * Assumptions (see the report):
 * - Each contract region ("Contract A") shows, once it has an accepted file,
 *   a heading named "Preview" and a disclosure button named "Preview"
 *   (`aria-expanded`, `aria-controls`), collapsed by default.
 * - Expanded: per accepted file, in order, a heading whose name contains the
 *   file name, the language label, then one `<li>` per block holding the
 *   block text (inside `<bdi>`), the part label and "Page N" when present.
 * - At most 200 blocks are rendered per file until a button "Show all…".
 * - "Hidden text removed" is a disclosure button inside the preview; one
 *   `<li>` per reason with its count and sample.
 * - Warnings: one `<li>` per warning with the message and an icon
 *   (`svg` or an `aria-hidden="true"` element).
 * - Locale keys under `upload.preview.*` and `upload.errors.not_implemented`
 *   (list in `NEW_KEYS` below).
 *
 * These tests fail until S3-T4 is implemented.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale, text, type FlatLocale } from "../test/locale-utils";
import {
  FakeFetch,
  canary,
  fileList,
  interpolate,
  jsonResponse,
  makeFile,
  okResponse,
  pluralBase,
  templateRegExp,
} from "../test/upload-fakes";
import * as UploadFormModule from "./UploadForm";

// S3-T5: a file with `ocr_pages` now starts OCR. Keep it pending here, so the
// preview still shows which pages need text recognition.
vi.mock("../ocr/ocrPdf", () => ({
  recognizePages: () => new Promise<never>(() => undefined),
}));

const EN = flattenLocale(enJson);
const UK = flattenLocale(ukJson);
const RU = flattenLocale(ruJson);

const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;

type Kind = "pdf" | "docx" | "text";
type Overrides = Record<string, unknown>;

const KIND_LABEL: Record<Kind, string> = { pdf: "PDF", docx: "Word document", text: "Text file" };

let server: FakeFetch;
/** Stage 3 body overrides per file object. */
let answers: Map<Blob, { kind: Kind; overrides: Overrides }>;

beforeEach(() => {
  resetBrowserEnv();
  answers = new Map();
  server = new FakeFetch();
  server.autoRespond = (body) => {
    const blob = body as Blob;
    const answer = answers.get(blob);
    return answer === undefined
      ? okResponse("text", blob.size)
      : okResponse(answer.kind, blob.size, answer.overrides);
  };
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetBrowserEnv();
  delete (globalThis as Record<string, unknown>).__xss;
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

function blocks(...texts: string[]): Overrides {
  return { blocks: texts.map((t) => ({ text: t, part: "body", page: null })) };
}

function file(name: string, kind: Kind, overrides: Overrides = {}): File {
  const f = makeFile(name, { content: `synthetic ${name}` });
  answers.set(f, { kind, overrides });
  return f;
}

/** Adds files to a contract and waits until each row shows its kind label. */
async function addAccepted(label: string, ...files: File[]): Promise<void> {
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error(`No file input in Contract ${label}`);
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList(files) } });
  });
  for (const f of files) {
    const kind = answers.get(f)?.kind ?? "text";
    await waitFor(() => {
      const row = within(region(label))
        .getAllByText(f.name)
        .map((el) => el.closest("li"))
        .find((li) => li !== null);
      expect(row?.textContent).toContain(KIND_LABEL[kind]);
    });
  }
}

// S3-T5: a PDF with `ocr_pages` is accepted and then waits for OCR, so its row
// shows the OCR status instead of the kind label.
async function addAwaitingOcr(label: string, f: File): Promise<void> {
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error(`No file input in Contract ${label}`);
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList([f]) } });
  });
  await waitFor(() => {
    const row = within(region(label))
      .getAllByText(f.name)
      .map((el) => el.closest("li"))
      .find((li) => li !== null);
    expect(row?.textContent).toMatch(/text recognition|Recognizing page/);
  });
}

function previewButton(label: string): HTMLElement {
  return within(region(label)).getByRole("button", { name: "Preview" });
}

function expand(button: HTMLElement): void {
  act(() => {
    fireEvent.click(button);
  });
}

async function openPreview(label: string): Promise<HTMLElement> {
  const button = previewButton(label);
  expand(button);
  await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("true"));
  return region(label);
}

/** Hidden by the `hidden` attribute or `display: none` on itself or an ancestor. */
function isHidden(element: Element): boolean {
  for (let el: Element | null = element; el !== null; el = el.parentElement) {
    if (el.hasAttribute("hidden")) {
      return true;
    }
    if (el instanceof HTMLElement && getComputedStyle(el).display === "none") {
      return true;
    }
  }
  return false;
}

function isShown(container: HTMLElement, value: string): boolean {
  return within(container)
    .queryAllByText(value)
    .some((el) => !isHidden(el));
}

function blockItem(container: HTMLElement, value: string): HTMLLIElement {
  const li = within(container)
    .getAllByText(value)
    .map((el) => el.closest("li"))
    .find((item): item is HTMLLIElement => item !== null);
  if (li === undefined) {
    throw new Error(`No <li> for ${JSON.stringify(value)}`);
  }
  return li;
}

function position(a: Node, b: Node): number {
  // Negative when `a` comes before `b` in document order.
  return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function key(locale: FlatLocale, base: string): string {
  const found = Object.keys(locale).find((k) => k === base || pluralBase(k) === base);
  if (found === undefined) {
    throw new Error(`Locale key ${base} is missing`);
  }
  return found;
}

const PARTS = {
  body: "Body",
  footnote: "Footnote",
  endnote: "Endnote",
  header: "Header",
  footer: "Footer",
  textbox: "Text box",
} as const;

const KNOWN_WARNINGS = [
  "not_read_altchunk",
  "not_read_object",
  "not_read_subdocument",
  "borderline_text",
  "pdf_edited",
  "external_reference",
] as const;

const NEW_KEYS = [
  "upload.preview.title",
  ...["en", "uk", "ru", "mixed", "unknown"].map((l) => `upload.preview.language.${l}`),
  ...Object.keys(PARTS).map((p) => `upload.preview.part.${p}`),
  "upload.preview.page",
  "upload.preview.showAll",
  "upload.preview.removed.title",
  ...KNOWN_WARNINGS.map((c) => `upload.preview.warning.${c}`),
  "upload.preview.warning.unknown",
  "upload.preview.ocrPages",
  "upload.errors.not_implemented",
];

describe("AC5 — i18n keys", () => {
  it.each(NEW_KEYS)("test_key_%s_exists_in_en_uk_ru", (base) => {
    for (const locale of [EN, UK, RU]) {
      expect(text(locale, key(locale, base))).toBeTruthy();
    }
  });

  it.each(NEW_KEYS)("test_key_%s_is_translated_in_uk_and_ru", (base) => {
    const en = text(EN, key(EN, base));
    expect(text(UK, key(UK, base))).not.toBe(en);
    expect(text(RU, key(RU, base))).not.toBe(en);
  });

  it.each(NEW_KEYS)("test_key_%s_has_same_placeholders_in_all_locales", (base) => {
    const names = (s: string) => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort();
    const en = names(text(EN, key(EN, base)));
    expect(names(text(UK, key(UK, base)))).toEqual(en);
    expect(names(text(RU, key(RU, base)))).toEqual(en);
  });

  it("test_en_copy_matches_acceptance_criteria", () => {
    expect(text(EN, "upload.preview.title")).toBe("Preview");
    for (const [part, label] of Object.entries(PARTS)) {
      expect(text(EN, `upload.preview.part.${part}`)).toBe(label);
    }
    expect(text(EN, key(EN, "upload.preview.showAll"))).toContain("Show all");
    expect(text(EN, "upload.preview.removed.title")).toBe("Hidden text removed");
    expect(text(EN, "upload.preview.warning.unknown")).toContain("Some content could not be read");
    expect(text(EN, "upload.errors.not_implemented")).toContain("PDF and Word support is coming");
    expect(text(EN, key(EN, "upload.preview.ocrPages"))).toContain("need");
    expect(text(EN, key(EN, "upload.preview.ocrPages"))).toContain("text recognition");
  });
});

describe("AC1 — 501 not_implemented in the file row", () => {
  it("test_501_not_implemented_row_says_pdf_and_word_support_is_coming", async () => {
    await renderForm();
    server.autoRespond = () => jsonResponse(501, { error: "not_implemented" });
    const input = region("A").querySelector<HTMLInputElement>('input[type="file"]');
    if (input === null) {
      throw new Error("No file input in Contract A");
    }
    act(() => {
      fireEvent.change(input, {
        target: { files: fileList([makeFile("main.pdf")]) },
      });
    });
    await waitFor(() =>
      expect(region("A").textContent).toContain(text(EN, "upload.errors.not_implemented")),
    );
  });
});

describe("AC3 — Preview disclosure", () => {
  it("test_preview_has_heading_and_button_collapsed_by_default", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", blocks("Alpha clause.")));
    expect(within(region("A")).getByRole("heading", { name: "Preview" })).toBeTruthy();
    expect(previewButton("A").getAttribute("aria-expanded")).toBe("false");
    expect(isShown(region("A"), "Alpha clause.")).toBe(false);
  });

  it("test_preview_button_controls_an_existing_element", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text"));
    await openPreview("A");
    const id = previewButton("A").getAttribute("aria-controls");
    expect(id).toBeTruthy();
    expect(document.getElementById(id ?? "")).not.toBeNull();
  });

  it("test_preview_expands_and_collapses", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", blocks("Alpha clause.")));
    const container = await openPreview("A");
    expect(isShown(container, "Alpha clause.")).toBe(true);
    expand(previewButton("A"));
    expect(previewButton("A").getAttribute("aria-expanded")).toBe("false");
    expect(isShown(region("A"), "Alpha clause.")).toBe(false);
  });

  it("test_preview_is_per_contract", async () => {
    await renderForm();
    await addAccepted("A", file("a.txt", "text", blocks("Alpha only.")));
    await addAccepted("B", file("b.txt", "text", blocks("Beta only.")));
    const a = await openPreview("A");
    expect(isShown(a, "Alpha only.")).toBe(true);
    expect(within(a).queryByText("Beta only.")).toBeNull();
    expect(previewButton("B").getAttribute("aria-expanded")).toBe("false");
  });
});

describe("AC3 — files, language labels and blocks", () => {
  it("test_files_are_listed_in_order_with_language_label", async () => {
    await renderForm();
    await addAccepted(
      "A",
      file("main.txt", "text", { language: "en", ...blocks("Main text.") }),
      file("annex.txt", "text", { language: "uk", ...blocks("Додаток.") }),
    );
    const container = await openPreview("A");
    const main = within(container).getByRole("heading", { name: /main\.txt/ });
    const annex = within(container).getByRole("heading", { name: /annex\.txt/ });
    const english = within(container).getByText(text(EN, "upload.preview.language.en"));
    const ukrainian = within(container).getByText(text(EN, "upload.preview.language.uk"));
    expect(position(main, english)).toBe(-1);
    expect(position(english, annex)).toBe(-1);
    expect(position(annex, ukrainian)).toBe(-1);
    expect(position(within(container).getByText("Main text."), annex)).toBe(-1);
  });

  it.each(["mixed", "unknown", "ru"])("test_language_%s_shows_its_label", async (language) => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", { language }));
    const container = await openPreview("A");
    expect(isShown(container, text(EN, `upload.preview.language.${language}`))).toBe(true);
  });

  it.each(Object.entries(PARTS))("test_block_part_%s_shows_label_%s", async (part, label) => {
    await renderForm();
    const blockText = `Synthetic ${part} text.`;
    await addAccepted(
      "A",
      file("main.docx", "docx", { blocks: [{ text: blockText, part, page: null }] }),
    );
    const container = await openPreview("A");
    expect(blockItem(container, blockText).textContent).toContain(label);
  });

  it("test_pdf_block_shows_page_number", async () => {
    await renderForm();
    await addAccepted(
      "A",
      file("main.pdf", "pdf", {
        pages: 3,
        blocks: [{ text: "Third page clause.", part: "body", page: 3 }],
      }),
    );
    const container = await openPreview("A");
    const page = interpolate(text(EN, "upload.preview.page"), { page: 3 });
    expect(blockItem(container, "Third page clause.").textContent).toContain(page);
  });

  it("test_page_label_has_no_extra_span_inside_the_meta_line", async () => {
    await renderForm();
    await addAccepted(
      "A",
      file("main.pdf", "pdf", {
        pages: 3,
        blocks: [{ text: "Third page clause.", part: "body", page: 3 }],
      }),
    );
    const container = await openPreview("A");
    const meta = blockItem(container, "Third page clause.").querySelector(".preview-block__meta");
    expect(meta?.textContent).toContain("Page 3");
    expect(meta?.querySelector("span")).toBeNull();
  });

  it("test_block_without_page_shows_no_page_label", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", blocks("No number clause.")));
    const container = await openPreview("A");
    const pagePrefix = text(EN, "upload.preview.page").split("{{")[0] ?? "";
    expect(blockItem(container, "No number clause.").textContent).not.toContain(pagePrefix.trim());
  });

  it("test_first_200_blocks_then_show_all", async () => {
    await renderForm();
    const many = Array.from({ length: 250 }, (_, i) => `Block ${i + 1}.`);
    await addAccepted("A", file("long.txt", "text", blocks(...many)));
    const container = await openPreview("A");
    expect(isShown(container, "Block 200.")).toBe(true);
    expect(within(container).queryByText("Block 201.")).toBeNull();
    const showAll = within(container).getByRole("button", { name: /^Show all/ });
    expand(showAll);
    expect(isShown(container, "Block 250.")).toBe(true);
    expect(within(container).queryByRole("button", { name: /^Show all/ })).toBeNull();
  });

  it("test_200_blocks_or_fewer_have_no_show_all", async () => {
    await renderForm();
    const exact = Array.from({ length: 200 }, (_, i) => `Block ${i + 1}.`);
    await addAccepted("A", file("exact.txt", "text", blocks(...exact)));
    const container = await openPreview("A");
    expect(isShown(container, "Block 200.")).toBe(true);
    expect(within(container).queryByRole("button", { name: /^Show all/ })).toBeNull();
  });
});

describe("AC4 — removed text", () => {
  const REMOVED = {
    removed: [
      { reason: "same_color", count: 4, sample: "white words sample" },
      { reason: "future_reason_code", count: 7, sample: "tiny words sample" },
    ],
  };

  function removedButton(container: HTMLElement): HTMLElement {
    return within(container).getByRole("button", { name: /^Hidden text removed/ });
  }

  it("test_removed_is_a_collapsed_disclosure", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", REMOVED));
    const container = await openPreview("A");
    expect(removedButton(container).getAttribute("aria-expanded")).toBe("false");
    expect(isShown(container, "white words sample")).toBe(false);
  });

  it("test_removed_shows_count_and_sample_per_reason", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", REMOVED));
    const container = await openPreview("A");
    expand(removedButton(container));
    expect(removedButton(container).getAttribute("aria-expanded")).toBe("true");
    expect(blockItem(container, "white words sample").textContent).toContain("4");
    expect(blockItem(container, "tiny words sample").textContent).toContain("7");
  });

  it("test_raw_reason_codes_are_not_shown", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text", REMOVED));
    const container = await openPreview("A");
    expand(removedButton(container));
    expect(container.textContent).not.toContain("same_color");
    expect(container.textContent).not.toContain("future_reason_code");
  });

  it("test_no_removed_text_shows_no_removed_button", async () => {
    await renderForm();
    await addAccepted("A", file("main.txt", "text"));
    const container = await openPreview("A");
    expect(within(container).queryByRole("button", { name: /^Hidden text removed/ })).toBeNull();
  });
});

describe("AC4 — warnings and OCR pages", () => {
  it.each(KNOWN_WARNINGS)("test_warning_%s_shows_icon_and_text", async (code) => {
    await renderForm();
    await addAccepted("A", file("main.docx", "docx", { warnings: [{ code, page: null }] }));
    const container = await openPreview("A");
    const item = blockItem(container, text(EN, `upload.preview.warning.${code}`));
    expect(item.querySelector('svg, [aria-hidden="true"]')).not.toBeNull();
  });

  it("test_unknown_warning_code_shows_generic_text_not_the_code", async () => {
    await renderForm();
    const code = "future_warning_code_x";
    await addAccepted("A", file("main.docx", "docx", { warnings: [{ code, page: null }] }));
    const container = await openPreview("A");
    const item = blockItem(container, text(EN, "upload.preview.warning.unknown"));
    expect(item.querySelector('svg, [aria-hidden="true"]')).not.toBeNull();
    expect(container.textContent).not.toContain(code);
  });

  it("test_ocr_pages_show_need_text_recognition_message", async () => {
    await renderForm();
    await addAwaitingOcr(
      "A",
      file("scan.pdf", "pdf", {
        pages: 4,
        blocks: [{ text: "Page one text.", part: "body", page: 1 }],
        ocr_pages: [2, 4],
      }),
    );
    const container = await openPreview("A");
    const template = text(EN, key(EN, "upload.preview.ocrPages"));
    const pattern = templateRegExp(template);
    const matches = Array.from(container.querySelectorAll("*")).filter(
      (el) => pattern.test(el.textContent.trim()) && !isHidden(el),
    );
    expect(matches.length).toBeGreaterThan(0);
    const message = matches[matches.length - 1]?.textContent ?? "";
    expect(message).toMatch(/2\D+4/);
  });

  it("test_no_ocr_pages_shows_no_ocr_message", async () => {
    await renderForm();
    await addAccepted("A", file("main.pdf", "pdf"));
    const container = await openPreview("A");
    expect(container.textContent).not.toContain("text recognition");
  });
});

describe("AC5 — untrusted text is plain text inside <bdi>", () => {
  const PAYLOADS = [
    '<img src=x onerror="globalThis.__xss=1">',
    "<script>globalThis.__xss=1</script>",
    "‮gnp.exe‬ clause with bidi override",
    "[click here](https://evil.example/x) and https://evil.example/y",
  ];

  async function renderPayloads(): Promise<HTMLElement> {
    await renderForm();
    await addAccepted(
      "A",
      file('<img src=x onerror="globalThis.__xss=1">.txt', "text", {
        ...blocks(...PAYLOADS),
        removed: [
          { reason: "same_color", count: 1, sample: "<script>globalThis.__xss=1</script>" },
        ],
      }),
    );
    const container = await openPreview("A");
    expand(within(container).getByRole("button", { name: /^Hidden text removed/ }));
    return container;
  }

  it.each(PAYLOADS)("test_block_%j_renders_literally_inside_bdi", async (payload) => {
    const container = await renderPayloads();
    // The payload can appear more than once (as a block and as a removed sample).
    const elements = within(container).getAllByText(payload);
    for (const element of elements) {
      expect(element.closest("bdi")).not.toBeNull();
    }
  });

  it("test_no_html_elements_are_created_from_text", async () => {
    const container = await renderPayloads();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector('a[href*="evil.example"]')).toBeNull();
    expect((globalThis as Record<string, unknown>).__xss).toBeUndefined();
  });

  it("test_file_name_in_preview_is_inside_bdi", async () => {
    const container = await renderPayloads();
    const heading = within(container).getByRole("heading", { name: /onerror/ });
    const nameElement = within(heading).getByText(/onerror/);
    expect(nameElement.closest("bdi")).not.toBeNull();
  });

  it("test_removed_sample_is_inside_bdi", async () => {
    const container = await renderPayloads();
    const samples = within(container).getAllByText("<script>globalThis.__xss=1</script>");
    expect(samples.length).toBeGreaterThan(1);
    for (const sample of samples) {
      expect(sample.closest("bdi")).not.toBeNull();
    }
  });
});

describe("AC2 — extraction stays in memory, never in storage", () => {
  it("test_contract_text_canary_is_not_written_to_storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const openDb = vi.fn();
    vi.stubGlobal("indexedDB", { open: openDb, deleteDatabase: vi.fn() });
    const secret = canary("CONTRACT-TEXT");
    await renderForm();
    await addAccepted("A", file("main.txt", "text", blocks(secret)));
    const container = await openPreview("A");
    expect(isShown(container, secret)).toBe(true);
    for (const call of setItem.mock.calls) {
      expect(JSON.stringify(call)).not.toContain(secret);
    }
    for (const storage of [localStorage, sessionStorage]) {
      for (let i = 0; i < storage.length; i += 1) {
        expect(storage.getItem(storage.key(i) ?? "") ?? "").not.toContain(secret);
      }
    }
    expect(openDb).not.toHaveBeenCalled();
  });
});
