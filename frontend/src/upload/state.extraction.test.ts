/**
 * S3-T4 AC2 — an accepted file keeps its extraction result in memory.
 *
 * Assumed interface: an `accepted` `UploadFile` has `extraction: Extraction`
 * (the object from `ExtractResult.extraction`). Rejected and pending files
 * have no `extraction`. Storage (never written) is tested in Preview.test.tsx.
 *
 * These tests fail until S3-T4 is implemented.
 */
import { describe, expect, it } from "vitest";
import type { ExtractResult } from "../api/extract";
import { okResult } from "../test/upload-fakes";
import { initialUploadState, uploadReducer, type UploadFile, type UploadState } from "./state";

const EXTRACTION_BODY = {
  language: "uk",
  blocks: [
    { text: "Пункт 1. Синтетичний текст.", part: "body", page: null },
    { text: "Примітка.", part: "footnote", page: null },
  ],
  removed: [{ reason: "hidden_formatting", count: 2, sample: "прихований" }],
  warnings: [{ code: "not_read_object", page: null }],
};

function withFile(): UploadState {
  return uploadReducer(initialUploadState, {
    type: "filesAdded",
    contractId: "contract-1",
    files: [{ id: "f1", name: "main.docx", size: 10 }],
  });
}

function check(state: UploadState, result: ExtractResult): UploadState {
  return uploadReducer(state, { type: "fileChecked", fileId: "f1", result });
}

function theFile(state: UploadState): UploadFile {
  const file = state.contracts[0]?.files[0];
  if (file === undefined) {
    throw new Error("no file");
  }
  return file;
}

describe("AC2 — extraction result kept per accepted file", () => {
  it("test_accepted_file_keeps_extraction_from_result", () => {
    const result = okResult("docx", 10, EXTRACTION_BODY);
    const file = theFile(check(withFile(), result));
    expect(file.status).toBe("accepted");
    expect(file).toMatchObject({ kind: "docx" });
    if (result.ok) {
      expect((file as unknown as { extraction: unknown }).extraction).toEqual(result.extraction);
    }
  });

  it("test_accepted_files_keep_their_own_extraction", () => {
    let state = uploadReducer(initialUploadState, {
      type: "filesAdded",
      contractId: "contract-1",
      files: [
        { id: "f1", name: "main.txt", size: 10 },
        { id: "f2", name: "annex.txt", size: 10 },
      ],
    });
    const first = okResult("text", 10, {
      blocks: [{ text: "First file.", part: "body", page: null }],
    });
    const second = okResult("text", 10, {
      language: "ru",
      blocks: [{ text: "Второй файл.", part: "body", page: null }],
    });
    state = uploadReducer(state, { type: "fileChecked", fileId: "f2", result: second });
    state = uploadReducer(state, { type: "fileChecked", fileId: "f1", result: first });
    const [a, b] = state.contracts[0]?.files ?? [];
    expect((a as unknown as { extraction: unknown }).extraction).toEqual(
      first.ok ? first.extraction : null,
    );
    expect((b as unknown as { extraction: unknown }).extraction).toEqual(
      second.ok ? second.extraction : null,
    );
  });

  it("test_rejected_file_has_no_extraction", () => {
    const file = theFile(check(withFile(), { ok: false, code: "unsupported_type" }));
    expect(file.status).toBe("rejected");
    expect("extraction" in file).toBe(false);
  });

  it("test_pending_file_has_no_extraction", () => {
    const file = theFile(withFile());
    expect("extraction" in file).toBe(false);
  });

  it("test_late_result_does_not_replace_kept_extraction", () => {
    const first = okResult("text", 10, {
      blocks: [{ text: "Kept.", part: "body", page: null }],
    });
    let state = check(withFile(), first);
    state = check(
      state,
      okResult("text", 10, {
        blocks: [{ text: "Late.", part: "body", page: null }],
      }),
    );
    expect((theFile(state) as unknown as { extraction: unknown }).extraction).toEqual(
      first.ok ? first.extraction : null,
    );
  });
});
