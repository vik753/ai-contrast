/**
 * S5-T2 review fixes (PR #55): shared request budget, coverage of the cleaned
 * blocks, and linear-time validation of a large block with astral characters.
 */
import { act, fireEvent, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
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
  requestBlocks,
  rowText,
  segmentOk,
  segmentReply,
  settle,
  waitSegmentCalls,
} from "../test/segment-fakes";
import { jsonResponse, makeFile, okResponse } from "../test/upload-fakes";

const EN = flattenLocale(enJson);
let servers: Servers;

beforeEach(() => {
  resetBrowserEnv();
  servers = new Servers();
  servers.extract.autoRespond = null;
  servers.install();
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18next.changeLanguage("en");
  resetBrowserEnv();
});

describe("shared request budget", () => {
  it("test_checks_and_splits_together_never_exceed_two_requests_in_flight", async () => {
    await renderForm();
    const names: string[] = [];
    for (const label of ["A", "B"]) {
      for (let i = 0; i < 3; i += 1) {
        const name = `${label}${String(i)}.docx`;
        names.push(name);
        addFile(servers, label, makeFile(name, { content: `content ${name}` }), [
          body(`Text of ${name}.`),
        ]);
      }
    }
    let maxInFlight = 0;
    const answered = new Set<unknown>();
    for (let step = 0; step < 400; step += 1) {
      const pendingExtract = servers.extract.pending();
      const pendingSegment = servers.segment.pending();
      maxInFlight = Math.max(maxInFlight, pendingExtract.length + pendingSegment.length);
      const next = [...pendingSegment, ...pendingExtract].find((c) => !answered.has(c));
      if (next === undefined) {
        if (
          names.every((n) => (document.body.textContent.split(n)[1] ?? "").includes("1 clause"))
        ) {
          break;
        }
        await settle(5);
        continue;
      }
      answered.add(next);
      if (servers.extract.calls.includes(next)) {
        const blob = next.body as Blob;
        act(() => {
          next.respond(
            okResponse("docx", blob.size, { blocks: servers.extractBlocks.get(blob) ?? [] }),
          );
        });
      } else {
        const blocks = requestBlocks(next);
        act(() => {
          next.respond(segmentOk(blocks));
        });
      }
      await settle(5);
    }
    expect(maxInFlight).toBeGreaterThan(0);
    expect(maxInFlight).toBeLessThanOrEqual(2);
    for (const name of names) {
      const label = name.slice(0, 1);
      await waitFor(() => {
        expect(rowText(label, name)).toMatch(/1 clause/);
      });
    }
  });
});

describe("coverage of the returned blocks", () => {
  async function reply(
    blocks: ReturnType<typeof body>[],
    spans: [number, number, number][][],
  ): Promise<void> {
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitFor(() => {
      expect(servers.extract.pending()).toHaveLength(1);
    });
    act(() => {
      servers.extract.calls[0]?.respond(
        okResponse("docx", (servers.extract.calls[0].body as Blob).size, { blocks }),
      );
    });
    await waitSegmentCalls(servers, 1);
    act(() => {
      servers.segment.calls[0]?.respond(
        jsonResponse(
          200,
          segmentReply(blocks, { clauses: spans.map((s, i) => clause(i + 1, { spans: s })) }),
        ),
      );
    });
  }
  const invalid = EN["upload.errors.invalid_response"] as string;

  it("test_uncovered_block_with_text_gives_invalid_response", async () => {
    await reply([body("Alpha beta."), body("Gamma delta.")], [[[0, 0, 11]]]);
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(invalid);
    });
  });

  it("test_uncovered_text_inside_a_block_gives_invalid_response", async () => {
    await reply(
      [body("Alpha beta."), body("Gamma delta.")],
      [
        [
          [0, 0, 5],
          [1, 0, 12],
        ],
      ],
    );
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toContain(invalid);
    });
  });

  it("test_uncovered_whitespace_only_is_accepted", async () => {
    await reply(
      [body("Alpha  beta."), body("   ")],
      [
        [
          [0, 0, 5],
          [0, 7, 12],
        ],
      ],
    );
    await waitFor(() => {
      expect(rowText("A", "a.docx")).toMatch(/1 clause/);
    });
    expect(rowText("A", "a.docx")).not.toContain(invalid);
  });
});

describe("linear-time validation", () => {
  it("test_one_million_characters_with_an_astral_and_2000_clauses_build_clause_text_fast", async () => {
    // Offsets are code points (Python). 1,000,000 code points, one is an emoji.
    const text = `${"a".repeat(10)}\u{1F600}${"a".repeat(999_989)}`;
    const blocks = [body(text)];
    await renderForm();
    addFile(servers, "A", makeFile("a.docx"), blocks);
    await waitFor(() => {
      expect(servers.extract.pending()).toHaveLength(1);
    });
    act(() => {
      servers.extract.calls[0]?.respond(
        okResponse("docx", (servers.extract.calls[0].body as Blob).size, { blocks }),
      );
    });
    await waitSegmentCalls(servers, 1);
    const clauses = Array.from({ length: 2000 }, (_, i) =>
      clause(i + 1, { spans: [[0, i * 500, i * 500 + 500]] }),
    );
    const payload = jsonResponse(200, segmentReply(blocks, { clauses }));
    const started = performance.now();
    act(() => {
      servers.segment.calls[0]?.respond(payload);
    });
    await waitFor(
      () => {
        expect(rowText("A", "a.docx")).toMatch(/2000 clauses/);
      },
      { timeout: 20_000 },
    );
    fireEvent.click(within(region("A")).getByRole("button", { name: "Preview" }));
    const clausesTab =
      within(region("A")).queryByRole("tab", { name: "Clauses" }) ??
      within(region("A")).getByRole("button", { name: "Clauses" });
    fireEvent.click(clausesTab);
    expect(performance.now() - started).toBeLessThan(1500);
  }, 30_000);
});
