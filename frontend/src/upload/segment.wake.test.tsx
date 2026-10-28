/**
 * A slot freed by an abort wakes a waiting clause split (shared budget, PR #55).
 */
import { act, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetBrowserEnv } from "../test/browser-env";
import {
  Servers,
  addFile,
  body,
  renderForm,
  row,
  rowText,
  settle,
  waitSegmentCalls,
} from "../test/segment-fakes";
import { jsonResponse, makeFile, okResponse } from "../test/upload-fakes";

let servers: Servers;

beforeEach(() => {
  resetBrowserEnv();
  servers = new Servers();
  servers.extract.autoRespond = null;
  servers.install();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

describe("budget release by abort", () => {
  it("test_removing_a_running_check_starts_a_waiting_split_without_further_input", async () => {
    await renderForm();
    // A row of Contract B whose split failed.
    const b = makeFile("b.docx", { content: "b" });
    addFile(servers, "B", b, [body("Text of b.")]);
    await waitFor(() => {
      expect(servers.extract.pending()).toHaveLength(1);
    });
    act(() => {
      servers.extract.calls[0]?.respond(
        okResponse("docx", b.size, { blocks: [body("Text of b.")] }),
      );
    });
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(422, { error: "segment_failed" })));
    await waitFor(() => {
      expect(within(row("B", "b.docx")).getByRole("button", { name: "Try again" })).toBeTruthy();
    });
    // Two checks of Contract A fill the budget.
    addFile(servers, "A", makeFile("a1.docx", { content: "1" }));
    addFile(servers, "A", makeFile("a2.docx", { content: "2" }));
    await waitFor(() => {
      expect(servers.extract.pending()).toHaveLength(2);
    });
    // The retry waits: no free slot.
    act(() => {
      fireEvent.click(within(row("B", "b.docx")).getByRole("button", { name: "Try again" }));
    });
    await settle();
    expect(servers.segment.calls).toHaveLength(1);
    // Removing one running check frees a slot: the split starts with no other input.
    act(() => {
      fireEvent.click(within(row("A", "a1.docx")).getByRole("button", { name: /^remove /i }));
    });
    await waitSegmentCalls(servers, 2);
    expect(rowText("B", "b.docx")).toContain("Splitting into clauses…");
  });
});
