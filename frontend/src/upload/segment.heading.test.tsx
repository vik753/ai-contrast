/**
 * Review of PR #61 (MAJOR, bug since PR #55): a clause may carry the heading of its
 * section, which lies in ANOTHER clause's spans (CLAUDE.md `/api/segment` example:
 * c2 spans [[1,0,37]], heading_span [0,3,10]). The client must accept that reply and
 * the preview must show the heading. A heading outside the returned blocks, or in
 * no clause at all, stays invalid.
 */
import { act, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { segmentBlocks } from "../api/segment";
import { resetBrowserEnv } from "../test/browser-env";
import {
  Servers,
  addFile,
  body,
  region,
  renderForm,
  rowText,
  waitSegmentCalls,
  type WireBlock,
} from "../test/segment-fakes";
import { jsonResponse, makeFile } from "../test/upload-fakes";

const BLOCKS: WireBlock[] = [body("1. Subject"), body("1.1. The insurer pays within 10 days.")];

function reply(
  blocks: WireBlock[],
  clauses: unknown[],
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    clauses,
    blocks,
    removed: [],
    warnings: [],
    detector_version: "det-1",
    entities: [],
    requisites: [],
    neutralized: [],
    ...extra,
  };
}
const c = (n: number, number_: string, level: number, spans: number[][], heading: number[]) => ({
  id: `c${String(n)}`,
  number: number_,
  level,
  part_index: 0,
  section_kind: null,
  part: "body",
  pages: [],
  spans,
  heading_span: heading,
});
const EXAMPLE = reply(BLOCKS, [
  c(1, "1", 1, [[0, 0, 10]], [0, 3, 10]),
  c(2, "1.1", 2, [[1, 0, 37]], [0, 3, 10]),
]);

const call = (r: Record<string, unknown>, blocks = BLOCKS) =>
  segmentBlocks(blocks, null, { fetchImpl: () => Promise.resolve(jsonResponse(200, r)) });

describe("heading of the section", () => {
  it("test_reply_where_subclause_carries_the_section_heading_is_accepted", async () => {
    expect((await call(EXAMPLE)).ok).toBe(true);
  });

  it("test_heading_span_outside_returned_blocks_is_invalid_response", async () => {
    for (const heading of [
      [0, 3, 999],
      [5, 0, 2],
    ]) {
      const r = reply(BLOCKS, [
        c(1, "1", 1, [[0, 0, 10]], [0, 3, 10]),
        c(2, "1.1", 2, [[1, 0, 37]], heading),
      ]);
      expect(await call(r)).toEqual({ ok: false, code: "invalid_response" });
    }
  });

  it("test_heading_span_inside_no_clause_is_invalid_response", async () => {
    // Block 1 is white space: it is in no clause, so a heading there belongs to nobody.
    const blocks = [body("1. Subject"), body("   "), body("1.1. The insurer pays.")];
    const r = reply(blocks, [
      c(1, "1", 1, [[0, 0, 10]], [0, 3, 10]),
      c(2, "1.1", 2, [[2, 0, 22]], [1, 0, 2]),
    ]);
    expect(await call(r, blocks)).toEqual({ ok: false, code: "invalid_response" });
  });
});

describe("preview of the section heading", () => {
  let servers: Servers;
  beforeEach(() => {
    resetBrowserEnv();
    servers = new Servers();
    servers.install();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    resetBrowserEnv();
  });

  it("test_preview_shows_subject_as_heading_of_clause_1_1", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), BLOCKS);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(200, EXAMPLE)));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/2 clauses/);
    });
    fireEvent.click(within(region("A")).getByRole("button", { name: "Preview" }));
    const root = region("A");
    const tab = ["tab", "radio", "button"]
      .map((role) => within(root).queryByRole(role, { name: "Clauses" }))
      .find((el) => el !== null);
    if (tab) {
      act(() => void fireEvent.click(tab));
    }
    const text = within(root).getByText(/The insurer pays within 10 days\./);
    const item = text.closest("li") ?? text.parentElement;
    expect(item?.textContent).toContain("1.1");
    expect(item?.textContent).toContain("Subject");
  });
});
