/** S3-T6b: reducer behavior for Google documents (rows without a local file). */
import { describe, expect, it } from "vitest";
import { MAX_FILE_BYTES, MAX_FILES_PER_CONTRACT } from "./limits";
import { initialUploadState, readiness, uploadReducer, type UploadState } from "./state";
import { okResult } from "../test/upload-fakes";

const CONTRACT = "contract-1";

function addDoc(state: UploadState, fileId: string, suffix = "abc123"): UploadState {
  return uploadReducer(state, { type: "googleDocAdded", contractId: CONTRACT, fileId, suffix });
}

function fileOf(state: UploadState, id: string) {
  return state.contracts.flatMap((c) => c.files).find((f) => f.id === id);
}

describe("google documents in the reducer", () => {
  it("test_added_document_is_queued_with_suffix_and_no_size", () => {
    const state = addDoc(initialUploadState, "file-1");
    expect(fileOf(state, "file-1")).toEqual({
      id: "file-1",
      name: "",
      size: 0,
      googleSuffix: "abc123",
      status: "queued",
    });
  });

  it("test_accepted_document_takes_size_from_the_server_and_keeps_suffix", () => {
    let state = addDoc(initialUploadState, "file-1");
    state = uploadReducer(state, { type: "fileCheckStarted", fileId: "file-1" });
    state = uploadReducer(state, {
      type: "fileChecked",
      fileId: "file-1",
      result: okResult("docx", 4096),
    });
    const file = fileOf(state, "file-1");
    expect(file?.status).toBe("accepted");
    expect(file?.size).toBe(4096);
    expect(file?.googleSuffix).toBe("abc123");
  });

  it("test_rejected_document_keeps_suffix", () => {
    let state = addDoc(initialUploadState, "file-1");
    state = uploadReducer(state, {
      type: "fileChecked",
      fileId: "file-1",
      result: { ok: false, code: "google_doc_not_public" },
    });
    expect(fileOf(state, "file-1")).toMatchObject({
      status: "rejected",
      code: "google_doc_not_public",
      googleSuffix: "abc123",
    });
  });

  it("test_document_over_the_file_limit_is_rejected", () => {
    let state = initialUploadState;
    for (let i = 0; i < MAX_FILES_PER_CONTRACT; i += 1) {
      state = addDoc(state, `file-${i}`);
    }
    state = addDoc(state, "file-extra");
    expect(fileOf(state, "file-extra")).toMatchObject({
      status: "rejected",
      code: "too_many_files",
    });
  });

  it("test_accepted_document_over_the_total_limit_is_rejected", () => {
    let state = addDoc(initialUploadState, "file-1");
    state = uploadReducer(state, {
      type: "filesAdded",
      contractId: "contract-2",
      files: Array.from({ length: 5 }, (_, i) => ({
        id: `big-${i}`,
        name: `big-${i}.pdf`,
        size: MAX_FILE_BYTES,
      })),
    });
    state = uploadReducer(state, {
      type: "fileChecked",
      fileId: "file-1",
      result: okResult("docx", 1024),
    });
    expect(fileOf(state, "file-1")).toMatchObject({ status: "rejected", code: "total_too_large" });
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });
});
