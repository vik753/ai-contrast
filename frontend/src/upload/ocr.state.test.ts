/**
 * S3-T5 AC5, AC6, AC7 — reducer part of the OCR flow (src/upload/state.ts).
 *
 * Assumed additions (see the report):
 * - result rule: a successful check with more than 30 `ocrPages` is rejected
 *   with code `too_many_ocr_pages` (30 is accepted);
 * - `needsOcr(file)`: accepted file with a non-empty `extraction.ocrPages`;
 * - actions: `ocrProgress {fileId,current,total}` sets `file.ocr = {current,total}`;
 *   `ocrFinished {fileId,pages:[{page,text,confidence}]}` merges the pages;
 *   `ocrFailed {fileId}` rejects the file with `ocr_failed`;
 * - merge: text split on blank lines into trimmed non-empty blocks
 *   `{part:"body", page}`; all blocks stable-sorted by page; `ocrPages` = [];
 *   `file.ocr` cleared; warning `ocr_used` for every OCR page and
 *   `ocr_low_confidence` for confidence < 60 (60 is fine); old warnings kept;
 * - caps after the merge (fail closed): more than 20,000 blocks or 1,000,000
 *   characters -> `too_much_text`; no block at all -> `no_text_extracted`;
 *   result pages different from `ocrPages` -> `ocr_failed`;
 * - `readiness` is `{ready:false, reason:"checking"}` while a file needs OCR.
 */
import { describe, expect, it } from "vitest";
import { MAX_BLOCKS, MAX_TEXT_CHARS, type Block } from "../api/extract";
import { okResult } from "../test/upload-fakes";
import {
  initialUploadState,
  needsOcr,
  readiness,
  uploadReducer,
  type UploadAction,
  type UploadFile,
  type UploadState,
} from "./state";

const act = (state: UploadState, ...actions: UploadAction[]): UploadState =>
  actions.reduce(uploadReducer, state);

function pdfBlock(text: string, page: number): Block {
  return { text, part: "body", page };
}

/** One PDF file (id f1) in contract A, checked with the given overrides. */
function withPdf(overrides: Record<string, unknown>): UploadState {
  return act(
    initialUploadState,
    {
      type: "filesAdded",
      contractId: "contract-1",
      files: [{ id: "f1", name: "scan.pdf", size: 10 }],
    },
    { type: "fileCheckStarted", fileId: "f1" },
    { type: "fileChecked", fileId: "f1", result: okResult("pdf", 10, overrides) },
  );
}

function file(state: UploadState): UploadFile {
  const found = state.contracts.flatMap((c) => c.files).find((f) => f.id === "f1");
  if (found === undefined) {
    throw new Error("file f1 is gone");
  }
  return found;
}

function accepted(state: UploadState) {
  const f = file(state);
  if (f.status !== "accepted") {
    throw new Error(`expected accepted, got ${f.status}`);
  }
  return f;
}

function rejectedCode(state: UploadState): string {
  const f = file(state);
  if (f.status !== "rejected") {
    throw new Error(`expected rejected, got ${f.status}`);
  }
  return f.code;
}

const SCAN = {
  pages: 4,
  blocks: [
    { text: "A1", part: "body", page: 1 },
    { text: "A4", part: "body", page: 4 },
  ],
  ocr_pages: [2, 3],
  warnings: [{ code: "pdf_edited", page: null }],
};

const finish = (state: UploadState, pages: { page: number; text: string; confidence: number }[]) =>
  uploadReducer(state, { type: "ocrFinished", fileId: "f1", pages });

describe("OCR page cap (AC5)", () => {
  it("test_thirty_ocr_pages_are_accepted", () => {
    const pages = Array.from({ length: 30 }, (_, i) => i + 1);
    const state = withPdf({ pages: 30, blocks: [], ocr_pages: pages });
    expect(accepted(state).extraction.ocrPages).toHaveLength(30);
  });

  it("test_thirty_one_ocr_pages_are_rejected_with_too_many_ocr_pages", () => {
    const pages = Array.from({ length: 31 }, (_, i) => i + 1);
    const state = withPdf({ pages: 31, blocks: [], ocr_pages: pages });
    expect(rejectedCode(state)).toBe("too_many_ocr_pages");
  });
});

describe("OCR state", () => {
  it("test_needs_ocr_is_true_for_accepted_file_with_ocr_pages", () => {
    expect(needsOcr(file(withPdf(SCAN)))).toBe(true);
  });

  it("test_needs_ocr_is_false_without_ocr_pages", () => {
    expect(needsOcr(file(withPdf({})))).toBe(false);
  });

  it("test_readiness_is_checking_while_a_file_needs_ocr", () => {
    const state = act(
      withPdf(SCAN),
      {
        type: "filesAdded",
        contractId: "contract-2",
        files: [{ id: "f2", name: "b.txt", size: 5 }],
      },
      { type: "fileCheckStarted", fileId: "f2" },
      { type: "fileChecked", fileId: "f2", result: okResult("text", 5) },
    );
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });

  it("test_readiness_is_ready_after_ocr_finished", () => {
    const state = act(
      withPdf(SCAN),
      {
        type: "filesAdded",
        contractId: "contract-2",
        files: [{ id: "f2", name: "b.txt", size: 5 }],
      },
      { type: "fileCheckStarted", fileId: "f2" },
      { type: "fileChecked", fileId: "f2", result: okResult("text", 5) },
      {
        type: "ocrFinished",
        fileId: "f1",
        pages: [
          { page: 2, text: "x", confidence: 90 },
          { page: 3, text: "y", confidence: 90 },
        ],
      },
    );
    expect(readiness(state)).toEqual({ ready: true, contracts: 2 });
  });

  it("test_ocr_progress_is_stored_on_the_file", () => {
    const state = uploadReducer(withPdf(SCAN), {
      type: "ocrProgress",
      fileId: "f1",
      current: 2,
      total: 2,
    });
    expect((accepted(state) as { ocr?: unknown }).ocr).toEqual({ current: 2, total: 2 });
  });

  it("test_ocr_failed_rejects_the_file_with_ocr_failed", () => {
    const state = uploadReducer(withPdf(SCAN), { type: "ocrFailed", fileId: "f1" });
    expect(rejectedCode(state)).toBe("ocr_failed");
  });

  it("test_ocr_finished_for_unknown_file_changes_nothing", () => {
    const state = withPdf(SCAN);
    expect(
      uploadReducer(state, {
        type: "ocrFinished",
        fileId: "gone",
        pages: [{ page: 2, text: "x", confidence: 90 }],
      }),
    ).toBe(state);
  });

  it("test_ocr_finished_after_file_removal_changes_nothing", () => {
    const removed = uploadReducer(withPdf(SCAN), {
      type: "fileRemoved",
      contractId: "contract-1",
      fileId: "f1",
    });
    expect(
      uploadReducer(removed, {
        type: "ocrFinished",
        fileId: "f1",
        pages: [{ page: 2, text: "x", confidence: 90 }],
      }),
    ).toBe(removed);
  });
});

describe("merge into the extraction (AC5)", () => {
  const PAGES = [
    { page: 3, text: "P3a\n\nP3b", confidence: 80 },
    { page: 2, text: "P2", confidence: 95 },
  ];

  it("test_merge_orders_blocks_by_page_and_keeps_paragraph_order", () => {
    const f = accepted(finish(withPdf(SCAN), PAGES));
    expect(f.extraction.blocks).toEqual([
      pdfBlock("A1", 1),
      pdfBlock("P2", 2),
      pdfBlock("P3a", 3),
      pdfBlock("P3b", 3),
      pdfBlock("A4", 4),
    ]);
  });

  it("test_merge_drops_empty_paragraphs_and_trims", () => {
    const f = accepted(
      finish(withPdf(SCAN), [
        { page: 2, text: "  \n\n  One  \n\n\n\n   \n\nTwo\n", confidence: 90 },
        { page: 3, text: "", confidence: 90 },
      ]),
    );
    expect(f.extraction.blocks.map((b) => b.text)).toEqual(["A1", "One", "Two", "A4"]);
  });

  it("test_merge_empties_ocr_pages_and_clears_progress", () => {
    const progress = uploadReducer(withPdf(SCAN), {
      type: "ocrProgress",
      fileId: "f1",
      current: 2,
      total: 2,
    });
    const f = accepted(finish(progress, PAGES));
    expect(f.extraction.ocrPages).toEqual([]);
    expect((f as { ocr?: unknown }).ocr).toBeUndefined();
    expect(needsOcr(f)).toBe(false);
  });

  it("test_merge_adds_ocr_used_for_every_ocr_page_and_keeps_old_warnings", () => {
    const f = accepted(finish(withPdf(SCAN), PAGES));
    const warnings = f.extraction.warnings;
    expect(warnings).toContainEqual({ code: "pdf_edited", page: null });
    expect(warnings).toContainEqual({ code: "ocr_used", page: 2 });
    expect(warnings).toContainEqual({ code: "ocr_used", page: 3 });
    expect(warnings.filter((w) => w.code === "ocr_used")).toHaveLength(2);
  });

  it("test_merge_confidence_below_60_adds_ocr_low_confidence_for_that_page", () => {
    const f = accepted(
      finish(withPdf(SCAN), [
        { page: 2, text: "P2", confidence: 59.9 },
        { page: 3, text: "P3", confidence: 95 },
      ]),
    );
    const low = f.extraction.warnings.filter((w) => w.code === "ocr_low_confidence");
    expect(low).toEqual([{ code: "ocr_low_confidence", page: 2 }]);
  });

  it("test_merge_confidence_exactly_60_is_not_low", () => {
    const f = accepted(
      finish(withPdf(SCAN), [
        { page: 2, text: "P2", confidence: 60 },
        { page: 3, text: "P3", confidence: 60 },
      ]),
    );
    expect(f.extraction.warnings.some((w) => w.code === "ocr_low_confidence")).toBe(false);
  });

  it("test_merge_keeps_the_file_kind_and_name", () => {
    const f = accepted(finish(withPdf(SCAN), PAGES));
    expect(f.kind).toBe("pdf");
    expect(f.name).toBe("scan.pdf");
  });

  it("test_merge_with_different_pages_than_ocr_pages_rejects_with_ocr_failed", () => {
    const state = finish(withPdf(SCAN), [
      { page: 2, text: "P2", confidence: 90 },
      { page: 7, text: "P7", confidence: 90 },
    ]);
    expect(rejectedCode(state)).toBe("ocr_failed");
  });

  it("test_merge_with_missing_page_rejects_with_ocr_failed", () => {
    const state = finish(withPdf(SCAN), [{ page: 2, text: "P2", confidence: 90 }]);
    expect(rejectedCode(state)).toBe("ocr_failed");
  });
});

describe("caps after the merge (AC7)", () => {
  it("test_merge_over_the_block_cap_rejects_with_too_much_text", () => {
    const blocks = Array.from({ length: MAX_BLOCKS - 1 }, (_, i) => ({
      text: `b${String(i)}`,
      part: "body",
      page: 1,
    }));
    const state = finish(withPdf({ pages: 2, blocks, ocr_pages: [2] }), [
      { page: 2, text: "one\n\ntwo", confidence: 90 },
    ]);
    expect(rejectedCode(state)).toBe("too_much_text");
  });

  it("test_merge_exactly_at_the_block_cap_is_accepted", () => {
    const blocks = Array.from({ length: MAX_BLOCKS - 1 }, (_, i) => ({
      text: `b${String(i)}`,
      part: "body",
      page: 1,
    }));
    const state = finish(withPdf({ pages: 2, blocks, ocr_pages: [2] }), [
      { page: 2, text: "one", confidence: 90 },
    ]);
    expect(accepted(state).extraction.blocks).toHaveLength(MAX_BLOCKS);
  });

  it("test_merge_over_the_character_cap_rejects_with_too_much_text", () => {
    const state = finish(withPdf({ pages: 2, blocks: [], ocr_pages: [2] }), [
      { page: 2, text: "x".repeat(MAX_TEXT_CHARS + 1), confidence: 90 },
    ]);
    expect(rejectedCode(state)).toBe("too_much_text");
  });

  it("test_merge_counts_server_text_and_ocr_text_together", () => {
    const state = finish(
      withPdf({
        pages: 2,
        blocks: [{ text: "y".repeat(MAX_TEXT_CHARS - 5), part: "body", page: 1 }],
        ocr_pages: [2],
      }),
      [{ page: 2, text: "x".repeat(10), confidence: 90 }],
    );
    expect(rejectedCode(state)).toBe("too_much_text");
  });

  it("test_merge_without_any_text_rejects_with_no_text_extracted", () => {
    const state = finish(withPdf({ pages: 2, blocks: [], ocr_pages: [1, 2] }), [
      { page: 1, text: "  \n\n ", confidence: 90 },
      { page: 2, text: "", confidence: 90 },
    ]);
    expect(rejectedCode(state)).toBe("no_text_extracted");
  });
});
