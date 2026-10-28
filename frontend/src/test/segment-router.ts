/**
 * Helpers for tests written before S5-T2: after extraction every row is split into
 * clauses, so these tests need a `/api/segment` answer. The fake echoes the blocks
 * of the request as one clause per block (a valid, complete reply).
 */
import { vi } from "vitest";
import type { Block } from "../api/extract";
import type { SegmentResult } from "../api/segment";
import {
  needsOcr,
  uploadReducer,
  type AcceptedFile,
  type UploadAction,
  type UploadState,
} from "../upload/state";
import { FakeFetch, jsonResponse } from "./upload-fakes";

function echoReply(body: unknown): Response {
  const blocks = (JSON.parse(String(body)) as { blocks: Block[] }).blocks;
  return jsonResponse(200, {
    clauses: blocks.map((block, index) => ({
      id: `c${String(index + 1)}`,
      number: null,
      level: 1,
      part_index: 0,
      section_kind: null,
      part: block.part,
      pages: block.page === null ? [] : [block.page],
      spans: [[index, 0, Array.from(block.text).length]],
      heading_span: null,
    })),
    blocks,
    removed: [],
    warnings: [],
  });
}

/** Routes `/api/segment` to an echo fake and everything else to `extract`. Returns the segment fake. */
export function routeFetch(extract: FakeFetch): FakeFetch {
  const segment = new FakeFetch();
  segment.autoRespond = echoReply;
  vi.stubGlobal("fetch", (input: unknown, init?: RequestInit) =>
    String(input).includes("/api/segment")
      ? segment.fetch(input, init)
      : extract.fetch(input, init),
  );
  return segment;
}

/** The actions of a finished clause split (start, echo reply) for one accepted row. */
export function splitActions(file: AcceptedFile): UploadAction[] {
  const blocks = file.extraction.blocks;
  const result: SegmentResult = {
    ok: true,
    segmentation: {
      clauses: blocks.map((block, index) => ({
        id: `c${String(index + 1)}`,
        number: null,
        level: 1,
        partIndex: 0,
        sectionKind: null,
        part: block.part,
        pages: block.page === null ? [] : [block.page],
        spans: [[index, 0, Array.from(block.text).length]],
        headingSpan: null,
      })),
      blocks,
      removed: [],
      warnings: [],
    },
  };
  return [
    { type: "segmentStarted", fileId: file.id },
    { type: "segmentFinished", fileId: file.id, result },
  ];
}

/** Runs the clause split for every row that waits for it. */
export function segmentAll(state: UploadState): UploadState {
  let next = state;
  for (const file of state.contracts.flatMap((c) => c.files)) {
    if (file.status === "accepted" && file.segment === undefined && !needsOcr(file)) {
      next = splitActions(file).reduce(uploadReducer, next);
    }
  }
  return next;
}
