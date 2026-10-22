/**
 * Review fixes for S3-T5: reducer details (empty OCR page, cleaning) and the
 * set of `File` objects that must be kept.
 */
import { describe, expect, it } from "vitest";
import { okResult } from "../test/upload-fakes";
import {
  fileIdsToKeep,
  initialUploadState,
  uploadReducer,
  type UploadAction,
  type UploadState,
} from "./state";

const act = (state: UploadState, ...actions: UploadAction[]): UploadState =>
  actions.reduce(uploadReducer, state);

function checked(id: string, overrides: Record<string, unknown> = {}): UploadAction[] {
  return [
    { type: "filesAdded", contractId: "contract-1", files: [{ id, name: `${id}.pdf`, size: 10 }] },
    { type: "fileCheckStarted", fileId: id },
    { type: "fileChecked", fileId: id, result: okResult("pdf", 10, overrides) },
  ];
}

const SCAN = {
  pages: 3,
  blocks: [{ text: "Server text.", part: "body", page: 1 }],
  ocr_pages: [2, 3],
};

function finished(pages: { page: number; text: string; confidence: number }[]) {
  const state = act(initialUploadState, ...checked("f1", SCAN), {
    type: "ocrFinished",
    fileId: "f1",
    pages,
  });
  const file = state.contracts[0]?.files[0];
  if (file?.status !== "accepted") {
    throw new Error("expected accepted");
  }
  return file;
}

describe("empty OCR page (fail visible)", () => {
  it("test_page_without_text_gets_the_low_confidence_warning", () => {
    const file = finished([
      { page: 2, text: "Clause two.", confidence: 95 },
      { page: 3, text: "  \n\n  ", confidence: 95 },
    ]);
    const low = file.extraction.warnings.filter((w) => w.code === "ocr_low_confidence");
    expect(low).toEqual([{ code: "ocr_low_confidence", page: 3 }]);
  });

  it("test_page_with_only_invisible_characters_counts_as_empty", () => {
    const file = finished([
      { page: 2, text: "Clause two.", confidence: 95 },
      { page: 3, text: "​⁠­", confidence: 95 },
    ]);
    expect(file.extraction.warnings).toContainEqual({ code: "ocr_low_confidence", page: 3 });
  });

  it("test_pages_with_text_and_good_confidence_have_no_low_warning", () => {
    const file = finished([
      { page: 2, text: "Clause two.", confidence: 95 },
      { page: 3, text: "Clause three.", confidence: 95 },
    ]);
    expect(file.extraction.warnings.some((w) => w.code === "ocr_low_confidence")).toBe(false);
  });
});

describe("OCR text cleaning", () => {
  it("test_default_ignorable_characters_are_removed", () => {
    // U+034F (combining grapheme joiner) and U+3164 (Hangul filler) are
    // default-ignorable but not in category Cf.
    const file = finished([
      { page: 2, text: "Pay\u034Fment\u3164 due", confidence: 95 },
      { page: 3, text: "Next.", confidence: 95 },
    ]);
    const texts = file.extraction.blocks.map((b) => b.text);
    expect(texts).toContain("Payment due");
    expect(texts.join("")).not.toMatch(/[\u3164\u034F]/u);
  });
});

describe("File references to keep", () => {
  it("test_queued_checking_and_ocr_files_are_kept", () => {
    const queued = act(initialUploadState, ...checked("f1").slice(0, 1));
    expect(fileIdsToKeep(queued)).toEqual(new Set(["f1"]));
    const checking = act(initialUploadState, ...checked("f1").slice(0, 2));
    expect(fileIdsToKeep(checking)).toEqual(new Set(["f1"]));
    const scan = act(initialUploadState, ...checked("f1", SCAN));
    expect(fileIdsToKeep(scan)).toEqual(new Set(["f1"]));
  });

  it("test_accepted_file_without_ocr_is_not_kept", () => {
    const state = act(initialUploadState, ...checked("f1"));
    expect(fileIdsToKeep(state).size).toBe(0);
  });

  it("test_file_is_dropped_once_ocr_finished", () => {
    const state = act(initialUploadState, ...checked("f1", SCAN), {
      type: "ocrFinished",
      fileId: "f1",
      pages: [
        { page: 2, text: "Two.", confidence: 90 },
        { page: 3, text: "Three.", confidence: 90 },
      ],
    });
    expect(fileIdsToKeep(state).size).toBe(0);
  });

  it("test_rejected_file_is_not_kept", () => {
    const state = act(initialUploadState, ...checked("f1", SCAN), {
      type: "ocrFailed",
      fileId: "f1",
    });
    expect(fileIdsToKeep(state).size).toBe(0);
  });
});
