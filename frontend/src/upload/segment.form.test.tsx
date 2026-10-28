/**
 * S5-T2 AC1, AC2, AC3, AC5 — clauses through the rendered upload form.
 *
 * Assumptions (black-box, from the task text):
 * - the request goes to "/api/segment" with a JSON string body
 *   `{"blocks":[{text,part,page}]}`, header `Content-Type: application/json`
 *   and the upload fetch options;
 * - the row shows "Splitting into clauses…" while the request runs and then
 *   "<N> clauses"; a failed row shows `upload.errors.<code>` and a button
 *   "Try again";
 * - the new error code `invalid_response` and the new server codes
 *   (`too_many_clauses`, `clause_too_long`, `segment_timeout`,
 *   `segment_failed`) have messages under `upload.errors.<code>`.
 *
 * These tests fail until S5-T2 is implemented.
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import {
  Servers,
  addFile,
  body,
  clause,
  region,
  removeFile,
  renderForm,
  requestBlocks,
  row,
  rowText,
  segmentOk,
  segmentReply,
  settle,
  waitSegmentCalls,
  type WireBlock,
} from "../test/segment-fakes";
import { busyResponse, jsonResponse, makeFile } from "../test/upload-fakes";

const EN = flattenLocale(enJson);
const UK = flattenLocale(ukJson);
const RU = flattenLocale(ruJson);

let servers: Servers;

beforeEach(() => {
  resetBrowserEnv();
  servers = new Servers();
  servers.install();
});

afterEach(async () => {
  vi.useRealTimers();
  await i18next.changeLanguage("en");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetBrowserEnv();
});

const SPLITTING = "Splitting into clauses…";

describe("AC1 — request body and options", () => {
  it("test_segment_request_sends_blocks_of_the_row_as_json", async () => {
    await renderForm();
    const blocks = [
      body("First paragraph."),
      { text: "A footnote.", part: "footnote", page: null },
    ];
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitSegmentCalls(servers, 1);
    const call = servers.segment.calls[0];
    expect(call?.input).toBe("/api/segment");
    expect(call?.init?.method?.toUpperCase()).toBe("POST");
    expect(typeof call?.body).toBe("string");
    const parsed = JSON.parse(String(call?.body)) as Record<string, unknown>;
    expect(Object.keys(parsed)).toEqual(["blocks"]);
    expect(parsed.blocks).toEqual(blocks);
  });

  it("test_segment_request_has_only_json_content_type_header", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    const headers = Array.from(new Headers(servers.segment.calls[0]?.init?.headers).entries());
    expect(headers).toEqual([["content-type", "application/json"]]);
  });

  it("test_segment_request_uses_upload_fetch_options", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    const init = servers.segment.calls[0]?.init;
    expect(init?.credentials).toBe("omit");
    expect(init?.redirect).toBe("error");
    expect(init?.cache).toBe("no-store");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("test_segment_request_has_no_file_name", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("secret-name-FNAME.docx"));
    await waitSegmentCalls(servers, 1);
    const call = servers.segment.calls[0];
    expect(String(call?.body)).not.toContain("FNAME");
    expect(String(call?.input)).not.toContain("FNAME");
  });

  it("test_segment_request_is_not_sent_before_extraction_answers", async () => {
    await renderForm();
    servers.extract.autoRespond = null;
    addFile(servers, "A", makeFile("a.docx"));
    await waitFor(() => {
      expect(servers.extract.calls).toHaveLength(1);
    });
    await settle();
    expect(servers.segment.calls).toHaveLength(0);
  });

  it("test_pdf_blocks_are_sent_in_the_order_of_the_extraction", async () => {
    await renderForm();
    const blocks = [body("Page one.", 1), body("Page two.", 2)];
    const file = makeFile("a.pdf");
    servers.extractOverrides.set(file, { pages: 2 });
    addFile(servers, "A", file, blocks);
    await waitSegmentCalls(servers, 1);
    expect(requestBlocks(servers.segment.calls[0] as { body: unknown })).toEqual(blocks);
  });

  it("test_at_most_two_segment_requests_are_in_flight", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a1.docx", { content: "one" }));
    addFile(servers, "A", makeFile("a2.docx", { content: "two" }));
    addFile(servers, "B", makeFile("b1.docx", { content: "three" }));
    addFile(servers, "B", makeFile("b2.docx", { content: "four" }));
    await waitSegmentCalls(servers, 2);
    await settle();
    expect(servers.segment.calls).toHaveLength(2);
    expect(servers.segment.pending()).toHaveLength(2);
    act(() => {
      servers.segment.calls[0]?.respond(segmentOk([body("Synthetic clause one.")]));
    });
    await waitSegmentCalls(servers, 3);
  });
});

describe("AC1 — busy retry (fake timers)", () => {
  async function startOne(): Promise<void> {
    await renderForm();
    vi.useFakeTimers();
    addFile(servers, "A", makeFile("a.docx"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(servers.segment.calls).toHaveLength(1);
  }
  const advance = (ms: number): Promise<void> =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  it("test_busy_segment_request_is_retried_after_retry_after", async () => {
    await startOne();
    act(() => servers.segment.calls[0]?.respond(busyResponse("5")));
    await advance(4_999);
    expect(servers.segment.calls).toHaveLength(1);
    await advance(1);
    expect(servers.segment.calls).toHaveLength(2);
    expect(servers.segment.calls[1]?.body).toBe(servers.segment.calls[0]?.body);
  });

  it("test_busy_segment_delay_is_capped_at_10_seconds", async () => {
    await startOne();
    act(() => servers.segment.calls[0]?.respond(busyResponse("120")));
    await advance(9_999);
    expect(servers.segment.calls).toHaveLength(1);
    await advance(1);
    expect(servers.segment.calls).toHaveLength(2);
  });
});

describe("AC1 — row text replaced by the cleaned blocks; hash from them", () => {
  it("test_preview_text_view_shows_cleaned_blocks_not_extracted_text", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), [body("Raw​ text RAWMARK.")]);
    await waitSegmentCalls(servers, 1);
    act(() => {
      servers.segment.calls[0]?.respond(segmentOk([body("Clean text CLEANMARK.")]));
    });
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/1 clause/);
    });
    fireEvent.click(within(region("A")).getByRole("button", { name: "Preview" }));
    const text = within(region("A"))
      .getAllByRole("button")
      .find((b) => b.textContent === "Text");
    if (text !== undefined) {
      fireEvent.click(text);
    } else {
      fireEvent.click(within(region("A")).getByRole("tab", { name: "Text" }));
    }
    expect(within(region("A")).getByText("Clean text CLEANMARK.")).toBeTruthy();
    expect(within(region("A")).queryByText(/RAWMARK/)).toBeNull();
  });

  it("test_text_hash_is_computed_from_cleaned_blocks_same_cleaned_text_is_flagged", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("one.docx", { content: "1" }), [body("Same​ text.")]);
    addFile(servers, "A", makeFile("two.docx", { content: "2" }), [body("Same text.")]);
    await waitSegmentCalls(servers, 2);
    act(() => {
      servers.segment.calls[0]?.respond(segmentOk([body("Same text.")]));
      servers.segment.calls[1]?.respond(segmentOk([body("Same text.")]));
    });
    await waitFor(() => {
      expect(screen.getAllByText(EN["upload.hash.sameTextHere"] as string).length).toBeGreaterThan(
        0,
      );
    });
  });

  it("test_text_hash_is_computed_from_cleaned_blocks_different_cleaned_text_is_not_flagged", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("one.docx", { content: "1" }), [body("Same text.")]);
    addFile(servers, "A", makeFile("two.docx", { content: "2" }), [body("Same text.")]);
    await waitSegmentCalls(servers, 2);
    act(() => {
      servers.segment.calls[0]?.respond(segmentOk([body("Cleaned one.")]));
      servers.segment.calls[1]?.respond(segmentOk([body("Cleaned two.")]));
    });
    await waitFor(() => {
      expect(rowText("A", "one.docx")).toMatch(/1 clause/);
      expect(rowText("A", "two.docx")).toMatch(/1 clause/);
    });
    await settle();
    expect(screen.queryByText(EN["upload.hash.sameTextHere"] as string)).toBeNull();
  });
});

describe("AC2 — row states", () => {
  it("test_row_shows_splitting_while_request_runs_then_clause_count", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), [body("One."), body("Two."), body("Three.")]);
    await waitSegmentCalls(servers, 1);
    expect(rowText("A", "a.docx")).toContain(SPLITTING);
    act(() => {
      servers.segment.calls[0]?.respond(segmentOk([body("One."), body("Two."), body("Three.")]));
    });
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/3 clauses/);
    });
    expect(rowText("A", "a.docx")).not.toContain(SPLITTING);
  });

  it("test_row_shows_singular_count_for_one_clause", async () => {
    await renderForm();
    servers.segmentAutomatically();
    addFile(servers, "A", makeFile("a.docx"));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/\b1 clause\b(?!s)/);
    });
  });
});

const CODES: [string, number][] = [
  ["invalid_request", 422],
  ["too_much_text", 422],
  ["no_text_extracted", 422],
  ["too_many_clauses", 422],
  ["clause_too_long", 422],
  ["segment_failed", 422],
  ["segment_timeout", 504],
  ["request_too_large", 413],
  ["upload_timeout", 408],
];

describe("AC2 — every segment error code, retry", () => {
  it.each(CODES)("test_segment_error_%s_is_shown_on_the_row_in_en", async (code, status) => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(status, { error: code })));
    const message = EN[`upload.errors.${code}`];
    expect(typeof message).toBe("string");
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(message as string);
    });
    expect(rowText("A", "a.docx")).not.toContain(code);
    expect(within(row("A", "a.docx")).getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it.each(CODES)("test_segment_error_%s_is_shown_in_uk_and_ru", async (code, status) => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    await act(async () => {
      await i18next.changeLanguage("uk");
    });
    act(() => servers.segment.calls[0]?.respond(jsonResponse(status, { error: code })));
    const uk = UK[`upload.errors.${code}`];
    const ru = RU[`upload.errors.${code}`];
    expect(typeof uk).toBe("string");
    expect(typeof ru).toBe("string");
    const text = (): string =>
      Array.from(document.querySelectorAll("li"))
        .filter((li) => li.textContent.includes("a.docx"))
        .map((li) => li.textContent)
        .join(" ");
    await waitFor(() => {
      expect(text()).toContain(uk as string);
    });
    await act(async () => {
      await i18next.changeLanguage("ru");
    });
    expect(text()).toContain(ru as string);
  });

  it("test_error_row_stays_in_the_contract_and_try_again_resends_the_same_body", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), [body("Retry me.")]);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(504, { error: "segment_timeout" })));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(EN["upload.errors.segment_timeout"] as string);
    });
    act(() => {
      fireEvent.click(within(row("A", "a.docx")).getByRole("button", { name: "Try again" }));
    });
    await waitSegmentCalls(servers, 2);
    expect(servers.segment.calls[1]?.body).toBe(servers.segment.calls[0]?.body);
    expect(rowText("A", "a.docx")).toContain(SPLITTING);
    act(() => servers.segment.calls[1]?.respond(segmentOk([body("Retry me.")])));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/1 clause/);
    });
    expect(rowText("A", "a.docx")).not.toContain(EN["upload.errors.segment_timeout"] as string);
    // The extraction is not repeated by a retry.
    expect(servers.extract.calls).toHaveLength(1);
  });

  it("test_network_failure_of_segment_request_is_shown_with_try_again", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.fail(new TypeError("Failed to fetch")));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(EN["upload.errors.network_error"] as string);
    });
    expect(within(row("A", "a.docx")).getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("AC1 — strict response validation (invalid_response)", () => {
  const blocks: WireBlock[] = [body("Alpha beta."), body("Gamma delta.")];
  const valid = (): Record<string, unknown> => segmentReply(blocks);
  const cases: [string, () => unknown][] = [
    [
      "span_block_index_out_of_range",
      () => ({ ...valid(), clauses: [clause(1, { spans: [[2, 0, 3]] })] }),
    ],
    [
      "span_end_past_block_text",
      () => ({ ...valid(), clauses: [clause(1, { spans: [[0, 0, 99]] })] }),
    ],
    ["span_start_after_end", () => ({ ...valid(), clauses: [clause(1, { spans: [[0, 5, 2]] })] })],
    [
      "spans_out_of_order_within_a_clause",
      () => ({
        ...valid(),
        clauses: [
          clause(1, {
            spans: [
              [1, 0, 4],
              [0, 0, 4],
            ],
          }),
        ],
      }),
    ],
    [
      "spans_overlap_inside_one_block_of_a_clause",
      () => ({
        ...valid(),
        clauses: [
          clause(1, {
            spans: [
              [0, 0, 6],
              [0, 3, 9],
            ],
          }),
        ],
      }),
    ],
    [
      "character_in_two_clauses",
      () => ({
        ...valid(),
        clauses: [clause(1, { spans: [[0, 0, 8]] }), clause(2, { spans: [[0, 5, 11]] })],
      }),
    ],
    [
      "heading_span_outside_blocks",
      () => ({ ...valid(), clauses: [clause(1, { spans: [[0, 0, 4]], heading_span: [5, 0, 1] })] }),
    ],
    ["clauses_missing", () => ({ blocks, removed: [], warnings: [] })],
    ["clauses_not_an_array", () => ({ ...valid(), clauses: "x" })],
    [
      "block_with_unknown_part",
      () => ({ ...valid(), blocks: [{ text: "x", part: "evil", page: null }] }),
    ],
    [
      "block_text_not_a_string",
      () => ({ ...valid(), blocks: [{ text: 5, part: "body", page: null }] }),
    ],
    [
      "clause_part_unknown",
      () => ({ ...valid(), clauses: [clause(1, { part: "evil", spans: [[0, 0, 3]] })] }),
    ],
    ["negative_offset", () => ({ ...valid(), clauses: [clause(1, { spans: [[0, -1, 3]] })] })],
    [
      "more_than_2000_clauses",
      () => {
        const many = Array.from({ length: 2001 }, () => body("x"));
        return segmentReply(many);
      },
    ],
    [
      "more_than_20000_blocks",
      () => ({
        ...valid(),
        blocks: Array.from({ length: 20_001 }, () => body("x")),
        clauses: [],
      }),
    ],
    [
      "more_than_1000000_characters",
      () => ({
        ...valid(),
        blocks: [body("a".repeat(600_000)), body("b".repeat(600_000))],
        clauses: [],
      }),
    ],
  ];

  it.each(cases)("test_invalid_segment_reply_%s_gives_invalid_response", async (_name, make) => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(200, make())));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(EN["upload.errors.invalid_response"] as string);
    });
    expect(within(row("A", "a.docx")).getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("test_non_json_200_segment_reply_gives_invalid_response", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(new Response("<html>", { status: 200 })));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(EN["upload.errors.invalid_response"] as string);
    });
  });

  it("test_valid_reply_with_clauses_covering_whole_blocks_is_accepted", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(segmentOk(blocks)));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/2 clauses/);
    });
  });
});

describe("AC3 — clauses stay in memory", () => {
  it("test_clauses_are_not_written_to_storage_console_url_or_announcements", async () => {
    const marker = "CLAUSE-CANARY-7731";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const href = window.location.href;
    const historyLength = window.history.length;
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), [body(`${marker} text.`)]);
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(segmentOk([body(`${marker} text.`)])));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/1 clause/);
    });
    await settle();
    expect(setItem).not.toHaveBeenCalled();
    consoleSpies.forEach((spy) => {
      expect(spy).not.toHaveBeenCalled();
    });
    expect(window.location.href).toBe(href);
    expect(window.history.length).toBe(historyLength);
    expect(window.location.href).not.toContain(marker);
    const live = Array.from(document.querySelectorAll("[aria-live], [role=status], [role=alert]"));
    expect(live.map((el) => el.textContent).join(" ")).not.toContain(marker);
    expect(JSON.stringify(Object.entries(localStorage))).not.toContain(marker);
    expect(JSON.stringify(Object.entries(sessionStorage))).not.toContain(marker);
  });

  it("test_error_replies_never_reach_console", async () => {
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    act(() => servers.segment.calls[0]?.respond(jsonResponse(200, { clauses: 1 })));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(EN["upload.errors.invalid_response"] as string);
    });
    consoleSpies.forEach((spy) => {
      expect(spy).not.toHaveBeenCalled();
    });
  });
});

describe("AC5 — readiness and removal", () => {
  const readyText = (n: number): string => `Ready to compare: ${String(n)} contracts`;

  it("test_contract_is_not_ready_until_every_row_has_clauses", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx", { content: "a" }));
    addFile(servers, "B", makeFile("b.docx", { content: "b" }));
    await waitSegmentCalls(servers, 2);
    await settle();
    expect(screen.queryByText(readyText(2))).toBeNull();
    act(() => servers.segment.calls[0]?.respond(segmentOk([body("Synthetic clause one.")])));
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/1 clause/);
    });
    await settle();
    expect(screen.queryByText(readyText(2))).toBeNull();
    act(() => servers.segment.calls[1]?.respond(segmentOk([body("Synthetic clause one.")])));
    expect(await screen.findByText(readyText(2))).toBeTruthy();
  });

  it("test_contract_with_a_segment_error_is_not_ready", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx", { content: "a" }));
    addFile(servers, "B", makeFile("b.docx", { content: "b" }));
    await waitSegmentCalls(servers, 2);
    act(() => servers.segment.calls[0]?.respond(segmentOk([body("Synthetic clause one.")])));
    act(() => servers.segment.calls[1]?.respond(jsonResponse(422, { error: "segment_failed" })));
    await waitFor(() => {
      expect(rowText("B", "b.docx")).toContain(EN["upload.errors.segment_failed"] as string);
    });
    await settle();
    expect(screen.queryByText(readyText(2))).toBeNull();
  });

  it("test_removing_a_row_aborts_its_segment_request", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    const signal = servers.segment.calls[0]?.signal;
    expect(signal?.aborted).toBe(false);
    removeFile("A");
    expect(signal?.aborted).toBe(true);
  });

  it("test_late_segment_reply_after_removal_is_ignored", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), [body("Ghost text.")]);
    await waitSegmentCalls(servers, 1);
    const call = servers.segment.calls[0];
    removeFile("A");
    act(() => call?.respond(segmentOk([body("Ghost text.")])));
    await settle();
    expect(screen.queryByText(/Ghost text/)).toBeNull();
    expect(within(region("A")).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("test_removing_the_row_frees_the_slot_for_the_next_segment_request", async () => {
    await renderForm();
    addFile(servers, "A", makeFile("a1.docx", { content: "1" }));
    addFile(servers, "A", makeFile("a2.docx", { content: "2" }));
    addFile(servers, "B", makeFile("b1.docx", { content: "3" }));
    await waitSegmentCalls(servers, 2);
    act(() => {
      fireEvent.click(within(row("A", "a1.docx")).getByRole("button", { name: /^remove /i }));
    });
    await waitSegmentCalls(servers, 3);
  });

  it("test_unmounting_the_form_aborts_segment_requests", async () => {
    const unmount = await renderForm();
    addFile(servers, "A", makeFile("a.docx"));
    await waitSegmentCalls(servers, 1);
    unmount();
    expect(servers.segment.calls[0]?.signal?.aborted).toBe(true);
  });
});
