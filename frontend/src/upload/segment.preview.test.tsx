/**
 * S5-T2 AC4 — the preview "Clauses" / "Text" switch.
 *
 * Assumptions: the switch is a tab, radio or button named "Clauses" / "Text"
 * inside the opened preview; the part labels of footnote/endnote/header/footer/
 * textbox are the existing `upload.preview.part.*` values, "running header" and
 * "preamble" labels match /running/i and /preamble/i, the badge matches
 * /requisites/i; a segment warning uses `upload.preview.warning.<code>` with an
 * icon (`svg[aria-hidden]`); long lists show 200 clauses and a button
 * "Show all N clauses".
 *
 * These tests fail until S5-T2 is implemented.
 */
import { act, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import {
  Servers,
  addFile,
  body,
  clause,
  region,
  renderForm,
  rowText,
  segmentReply,
  waitSegmentCalls,
  type WireBlock,
} from "../test/segment-fakes";
import { jsonResponse, makeFile } from "../test/upload-fakes";

const EN = flattenLocale(enJson);
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

async function openPreview(
  reply: Record<string, unknown>,
  sent?: WireBlock[],
): Promise<HTMLElement> {
  await renderForm();
  addFile(servers, "A", makeFile("a.docx"), sent ?? (reply.blocks as WireBlock[]));
  await waitSegmentCalls(servers, 1);
  act(() => servers.segment.calls[0]?.respond(jsonResponse(200, reply)));
  await waitFor(() => {
    expect(rowText("A", "a.docx")).toMatch(/\d+ clauses?/);
  });
  fireEvent.click(within(region("A")).getByRole("button", { name: "Preview" }));
  return region("A");
}

function control(root: HTMLElement, name: string): HTMLElement {
  for (const role of ["tab", "radio", "button"]) {
    const found = within(root).queryByRole(role, { name });
    if (found !== null) {
      return found;
    }
  }
  throw new Error(`No switch named ${name}`);
}

function pick(root: HTMLElement, name: string): void {
  act(() => {
    fireEvent.click(control(root, name));
  });
}

const BLOCKS: WireBlock[] = [
  body("Payment"),
  body("The client pays within thirty days."),
  { text: "A note about delivery.", part: "footnote", page: null },
  body("Page 1 of 9"),
  body("Preamble sentence here."),
  body("Bank details follow."),
];

function sample(): Record<string, unknown> {
  return segmentReply(BLOCKS, {
    clauses: [
      clause(1, {
        number: "3.2",
        spans: [
          [0, 0, 7],
          [1, 0, 35],
        ],
        heading_span: [0, 0, 7],
      }),
      clause(2, { part: "footnote", spans: [[2, 0, 22]] }),
      clause(3, { part: "running", spans: [[3, 0, 11]] }),
      clause(4, { part: "preamble", level: 0, spans: [[4, 0, 23]] }),
      clause(5, { number: "9", section_kind: "requisites", spans: [[5, 0, 20]] }),
    ],
    warnings: [{ code: "numbering_gap", clause: "c2" }],
  });
}

describe("AC4 — switch", () => {
  it("test_clauses_view_shows_number_heading_and_text", async () => {
    const root = await openPreview(sample());
    pick(root, "Clauses");
    expect(within(root).getByText(/3\.2/)).toBeTruthy();
    expect(within(root).getAllByText(/Payment/).length).toBeGreaterThan(0);
    expect(within(root).getByText(/The client pays within thirty days\./)).toBeTruthy();
  });

  it("test_heading_is_read_from_heading_span_not_from_a_separate_field", async () => {
    const reply = sample();
    const root = await openPreview(reply);
    pick(root, "Clauses");
    const heading = within(root).getAllByText(/Payment/)[0];
    expect(heading?.textContent).toContain("Payment");
    expect(heading?.textContent).not.toContain("Pay ment");
  });

  it("test_clauses_view_shows_part_label_for_footnote_running_and_preamble", async () => {
    const root = await openPreview(sample());
    pick(root, "Clauses");
    expect(
      within(root).getAllByText(EN["upload.preview.part.footnote"] as string).length,
    ).toBeGreaterThan(0);
    expect(within(root).getAllByText(/running/i).length).toBeGreaterThan(0);
    expect(within(root).getAllByText(/preamble/i).length).toBeGreaterThan(0);
  });

  it("test_requisites_badge_is_shown_for_requisites_clause_only", async () => {
    const root = await openPreview(sample());
    pick(root, "Clauses");
    expect(within(root).getAllByText(/requisites/i)).toHaveLength(1);
  });

  it("test_segment_warning_is_shown_with_icon_and_text", async () => {
    const root = await openPreview(sample());
    pick(root, "Clauses");
    const text = within(root).getByText(EN["upload.preview.warning.numbering_gap"] as string);
    expect(text.closest("li")?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it("test_text_view_shows_blocks_and_hides_clause_features", async () => {
    const root = await openPreview(sample());
    pick(root, "Clauses");
    pick(root, "Text");
    expect(within(root).getByText("The client pays within thirty days.")).toBeTruthy();
    expect(within(root).queryByText(/requisites/i)).toBeNull();
    expect(
      within(root).queryByText(EN["upload.preview.warning.numbering_gap"] as string),
    ).toBeNull();
  });

  it("test_switching_back_to_clauses_shows_them_again", async () => {
    const root = await openPreview(sample());
    pick(root, "Text");
    pick(root, "Clauses");
    expect(within(root).getAllByText(/requisites/i)).toHaveLength(1);
  });
});

describe("AC4 — caps and Show all", () => {
  const many = (n: number): WireBlock[] =>
    Array.from({ length: n }, (_, i) => body(`Clause body ${String(i + 1)}.`));

  it("test_clauses_view_renders_200_clauses_and_show_all_renders_the_rest", async () => {
    const blocks = many(250);
    const root = await openPreview(segmentReply(blocks));
    pick(root, "Clauses");
    expect(within(root).getAllByText(/^Clause body \d+\.$/)).toHaveLength(200);
    fireEvent.click(within(root).getByRole("button", { name: /Show all 250/ }));
    expect(within(root).getAllByText(/^Clause body \d+\.$/)).toHaveLength(250);
  });

  it("test_no_show_all_button_for_a_short_list", async () => {
    const root = await openPreview(segmentReply(many(5)));
    pick(root, "Clauses");
    expect(within(root).queryByRole("button", { name: /Show all/ })).toBeNull();
  });
});

describe("AC4 / T6 — plain text only", () => {
  const evil = '<img src=x onerror="alert(1)"> [link](https://evil.example) <script>1</script>';

  it("test_clause_text_with_markup_is_rendered_as_plain_text", async () => {
    const root = await openPreview(segmentReply([body(evil)]));
    pick(root, "Clauses");
    expect(within(root).getByText(evil)).toBeTruthy();
    expect(root.querySelector("img, script, a")).toBeNull();
  });

  it("test_heading_with_markup_is_rendered_as_plain_text", async () => {
    const heading = '<b onmouseover="x">Head</b> [h](https://evil.example)';
    const blocks = [body(heading), body("Text under it.")];
    const root = await openPreview(
      segmentReply(blocks, {
        clauses: [
          clause(1, {
            number: "1",
            spans: [
              [0, 0, heading.length],
              [1, 0, 14],
            ],
            heading_span: [0, 0, heading.length],
          }),
        ],
      }),
    );
    pick(root, "Clauses");
    expect(within(root).getAllByText(heading, { exact: false }).length).toBeGreaterThan(0);
    expect(root.querySelector("b, a, img, script")).toBeNull();
  });

  it("test_clause_number_with_markup_is_rendered_as_plain_text", async () => {
    const number = "<i>1</i>";
    const root = await openPreview(
      segmentReply([body("Some text here.")], {
        clauses: [clause(1, { number, spans: [[0, 0, 15]] })],
      }),
    );
    pick(root, "Clauses");
    expect(root.querySelector("i")).toBeNull();
  });
});
