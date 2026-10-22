/**
 * Review fix for S3-T5: after an abort, the next OCR job starts only when the
 * aborted job has settled (never two engines at once).
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { okResult } from "../test/upload-fakes";
import { initialUploadState, uploadReducer, type UploadAction, type UploadState } from "./state";
import { useOcrScheduler } from "./useOcrScheduler";

interface Job {
  name: string;
  signal: AbortSignal;
  finish: () => void;
}
const h = vi.hoisted(() => ({ jobs: [] as unknown[] }));

vi.mock("../ocr/ocrPdf", () => ({
  recognizePages: (file: File, _pages: unknown, opts: { signal: AbortSignal }) =>
    new Promise((_, reject) => {
      // Rejects only when the test says so, even after the abort.
      h.jobs.push({ name: file.name, signal: opts.signal, finish: () => reject(new Error("x")) });
    }),
}));

const jobs = (): Job[] => h.jobs as Job[];

afterEach(() => {
  h.jobs.length = 0;
});

function scanState(): UploadState {
  const add = (id: string, contractId: string): UploadAction[] => [
    { type: "filesAdded", contractId, files: [{ id, name: `${id}.pdf`, size: 10 }] },
    { type: "fileCheckStarted", fileId: id },
    {
      type: "fileChecked",
      fileId: id,
      result: okResult("pdf", 10, { pages: 2, blocks: [], ocr_pages: [1] }),
    },
  ];
  return [
    ...add("f1", "contract-1"),
    { type: "contractAdded" } as UploadAction,
    ...add("f2", "contract-2"),
  ].reduce(uploadReducer, initialUploadState);
}

describe("useOcrScheduler", () => {
  it("test_next_job_waits_for_the_aborted_job_to_settle", async () => {
    const files = new Map([
      ["f1", new File(["a"], "f1.pdf")],
      ["f2", new File(["b"], "f2.pdf")],
    ]);
    const dispatch = vi.fn();
    const { rerender } = renderHook(
      ({ state }: { state: UploadState }) =>
        useOcrScheduler(state, dispatch, (id) => files.get(id)),
      { initialProps: { state: scanState() } },
    );
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    expect(jobs()[0]?.name).toBe("f1.pdf");

    // Remove f1: its job is aborted, but its promise has not settled yet.
    const removed = uploadReducer(scanState(), {
      type: "fileRemoved",
      contractId: "contract-1",
      fileId: "f1",
    });
    rerender({ state: removed });
    expect(jobs()[0]?.signal.aborted).toBe(true);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(jobs()).toHaveLength(1);

    await act(async () => {
      jobs()[0]?.finish();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(jobs()).toHaveLength(2);
    });
    expect(jobs()[1]?.name).toBe("f2.pdf");
  });
});
