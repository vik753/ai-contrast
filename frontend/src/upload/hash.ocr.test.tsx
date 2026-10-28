/** S4-T1 AC5 — a row that becomes accepted after OCR gets its text hash and warnings. */
import { renderHook, waitFor } from "@testing-library/react";
import { useReducer } from "react";
import { describe, expect, it } from "vitest";
import { sha256Hex } from "../hash/sha256";
import { normalizeForHash } from "../hash/normalize";
import { okResult } from "../test/upload-fakes";
import {
  hashNotes,
  initialUploadState,
  uploadReducer,
  type AcceptedFile,
  type UploadAction,
} from "./state";
import { useHashing } from "./useHashing";

const TEXT = "The parties agree.";
const acts: UploadAction[] = [
  {
    type: "filesAdded",
    contractId: "contract-1",
    files: [
      { id: "scan", name: "scan.pdf", size: 10 },
      { id: "txt", name: "a.txt", size: 10 },
    ],
  },
  { type: "fileCheckStarted", fileId: "scan" },
  { type: "fileCheckStarted", fileId: "txt" },
  {
    type: "fileChecked",
    fileId: "scan",
    result: okResult("pdf", 10, { pages: 1, ocr_pages: [1], blocks: [] }),
  },
  {
    type: "fileChecked",
    fileId: "txt",
    result: okResult("text", 10, { blocks: [{ text: TEXT, part: "body", page: null }] }),
  },
];

describe("text hash after OCR", () => {
  it("test_scan_gets_a_text_hash_and_a_warning_only_after_ocr_finished", async () => {
    const { result } = renderHook(() => {
      const [state, dispatch] = useReducer(uploadReducer, initialUploadState, (s) =>
        acts.reduce(uploadReducer, s),
      );
      useHashing(state, dispatch, () => undefined);
      return { state, dispatch };
    });
    const files = (): AcceptedFile[] =>
      result.current.state.contracts
        .flatMap((c) => c.files)
        .filter((f): f is AcceptedFile => f.status === "accepted");
    const expected = await sha256Hex(normalizeForHash(TEXT));
    await waitFor(() => {
      expect(files().find((f) => f.id === "txt")?.textHash).toBe(expected);
    });
    // The scan still waits for OCR: no hash, no note.
    expect(files().find((f) => f.id === "scan")?.textHash).toBeUndefined();
    expect(hashNotes(result.current.state).get("scan")).toBeUndefined();

    result.current.dispatch({
      type: "ocrFinished",
      fileId: "scan",
      pages: [{ page: 1, text: TEXT, confidence: 90 }],
    });
    await waitFor(() => {
      expect(files().find((f) => f.id === "scan")?.textHash).toBe(expected);
    });
    expect(hashNotes(result.current.state).get("scan")).toEqual([{ type: "sameTextHere" }]);
    expect(
      files()
        .find((f) => f.id === "scan")
        ?.extraction.warnings.map((w) => w.code),
    ).toContain("ocr_used");
  });
});
