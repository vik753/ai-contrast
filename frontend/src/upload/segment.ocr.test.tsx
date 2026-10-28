/**
 * S5-T2 AC1 — a scanned PDF is segmented only after OCR, with the OCR blocks
 * in page order. `../ocr/ocrPdf` is mocked (same contract as ocr.form.test.tsx).
 * Assumption: OCR blocks are sent as `{text, part: "body", page}`.
 *
 * These tests fail until S5-T2 is implemented.
 */
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetBrowserEnv } from "../test/browser-env";
import {
  Servers,
  addFile,
  body,
  renderForm,
  requestBlocks,
  segmentOk,
  settle,
  waitSegmentCalls,
} from "../test/segment-fakes";
import { makeFile } from "../test/upload-fakes";

interface Job {
  resolve: (r: { page: number; text: string; confidence: number }[]) => void;
}
const h = vi.hoisted(() => ({ jobs: [] as unknown[] }));

vi.mock("../ocr/ocrPdf", () => ({
  recognizePages: (_file: File, _pages: readonly number[], opts: Record<string, unknown>) =>
    new Promise((resolve, reject) => {
      h.jobs.push({ resolve });
      (opts.signal as AbortSignal).addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      });
    }),
}));

let servers: Servers;

beforeEach(() => {
  resetBrowserEnv();
  h.jobs.length = 0;
  servers = new Servers();
  servers.install();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

describe("AC1 — OCR pages", () => {
  async function startScan(): Promise<void> {
    await renderForm();
    const file = makeFile("scan.pdf");
    servers.extractOverrides.set(file, { pages: 4, ocr_pages: [2, 4] });
    addFile(servers, "A", file, [body("Text of page one.", 1), body("Text of page three.", 3)]);
    await waitFor(() => {
      expect(h.jobs).toHaveLength(1);
    });
  }

  it("test_segment_request_waits_for_ocr_to_finish", async () => {
    await startScan();
    await settle();
    expect(servers.segment.calls).toHaveLength(0);
  });

  it("test_segment_request_contains_ocr_blocks_in_page_order", async () => {
    await startScan();
    await act(async () => {
      (h.jobs[0] as Job).resolve([
        { page: 4, text: "OCR page four.", confidence: 90 },
        { page: 2, text: "OCR page two.", confidence: 90 },
      ]);
      await Promise.resolve();
    });
    await waitSegmentCalls(servers, 1);
    const blocks = requestBlocks(servers.segment.calls[0] as { body: unknown });
    expect(blocks.map((b) => b.page)).toEqual([1, 2, 3, 4]);
    expect(blocks.map((b) => b.text)).toEqual([
      "Text of page one.",
      "OCR page two.",
      "Text of page three.",
      "OCR page four.",
    ]);
    expect(blocks.every((b) => b.part === "body")).toBe(true);
    act(() => servers.segment.calls[0]?.respond(segmentOk(blocks)));
  });
});
