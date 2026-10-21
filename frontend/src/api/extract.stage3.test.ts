/**
 * S3-T4 AC1 — `extractFile` validates the stage 3 `200` contract strictly
 * (docs/agent/TASKS.md, "Response contract: POST /api/extract 200 from stage 3").
 * Threats: T1 (server text never shown unvalidated), T3, T5.
 *
 * Assumed public interface of `src/api/extract.ts` (see the report):
 * - ok result: `{ ok: true, kind, bytes, extraction: Extraction }`;
 * - `Extraction` = `{ language, pages, blocks, ocrPages, removed, warnings }`
 *   (wire `ocr_pages` becomes `ocrPages`; blocks, removed and warnings keep
 *   their wire field names: `text`/`part`/`page`, `reason`/`count`/`sample`,
 *   `code`/`page`);
 * - unknown fields are rejected (the server model is `extra="forbid"`);
 * - client caps equal the server caps: 20,000 blocks, 1,000,000 characters
 *   of block text, a removed sample of at most 200 characters;
 * - new server code `not_implemented`, valid with status 501 only.
 *
 * These tests fail until S3-T4 is implemented.
 */
import { describe, expect, it } from "vitest";
import { extractFile, type ExtractErrorCode, type ExtractResult } from "./extract";
import {
  FakeFetch,
  jsonResponse,
  makeFile,
  okResponse,
  okResult,
  stage3Body,
} from "../test/upload-fakes";

const FILE_SIZE = 5;
const file = (): File => makeFile("a.bin", { content: "12345" });

async function extractWith(response: Response): Promise<ExtractResult> {
  const fake = new FakeFetch();
  fake.autoRespond = () => response;
  return extractFile(file(), { fetchImpl: fake.asFetch() });
}

function expectError(result: ExtractResult, code: ExtractErrorCode): void {
  expect(result.ok).toBe(false);
  if (!result.ok) {
    expect(result.code).toBe(code);
  }
}

async function expectInvalid(body: unknown): Promise<void> {
  expectError(await extractWith(jsonResponse(200, body)), "unknown_error");
}

async function expectValid(body: Record<string, unknown>): Promise<void> {
  const kind = body.kind as "pdf" | "docx" | "text";
  expect(await extractWith(jsonResponse(200, body))).toEqual(okResult(kind, FILE_SIZE, body));
}

const pdf = (overrides: Record<string, unknown> = {}) => stage3Body("pdf", FILE_SIZE, overrides);
const text = (overrides: Record<string, unknown> = {}) => stage3Body("text", FILE_SIZE, overrides);
const docx = (overrides: Record<string, unknown> = {}) => stage3Body("docx", FILE_SIZE, overrides);

function without(body: Record<string, unknown>, key: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(body).filter(([name]) => name !== key));
}

describe("AC1 — a valid stage 3 body", () => {
  it.each(["pdf", "docx", "text"] as const)("test_valid_%s_body_is_ok", async (kind) => {
    const result = await extractWith(okResponse(kind, FILE_SIZE));
    expect(result).toEqual(okResult(kind, FILE_SIZE));
  });

  it("test_full_pdf_body_maps_every_field_to_extraction", async () => {
    const body = pdf({
      language: "mixed",
      pages: 4,
      blocks: [
        { text: "Clause 1.", part: "body", page: 1 },
        { text: "Note.", part: "footnote", page: 2 },
        { text: "End note.", part: "endnote", page: 3 },
        { text: "Top.", part: "header", page: 4 },
        { text: "Bottom.", part: "footer", page: 4 },
        { text: "Box.", part: "textbox", page: 4 },
      ],
      ocr_pages: [2, 4],
      removed: [{ reason: "same_color", count: 4, sample: "hidden words" }],
      warnings: [
        { code: "borderline_text", page: 2 },
        { code: "something_new", page: null },
      ],
    });
    const result = await extractWith(jsonResponse(200, body));
    expect(result).toEqual({
      ok: true,
      kind: "pdf",
      bytes: FILE_SIZE,
      extraction: {
        language: "mixed",
        pages: 4,
        blocks: body.blocks,
        ocrPages: [2, 4],
        removed: body.removed,
        warnings: body.warnings,
      },
    });
  });

  it.each(["uk", "ru", "en", "mixed", "unknown"])("test_language_%s_is_accepted", async (lang) => {
    await expectValid(text({ language: lang }));
  });

  it("test_docx_with_null_pages_and_pages_of_blocks_is_ok", async () => {
    await expectValid(
      docx({
        blocks: [
          { text: "A.", part: "body", page: null },
          { text: "B.", part: "textbox", page: null },
        ],
        warnings: [{ code: "not_read_object", page: null }],
      }),
    );
  });

  it("test_empty_lists_except_blocks_are_ok", async () => {
    await expectValid(text({ ocr_pages: [], removed: [], warnings: [] }));
  });

  it("test_unknown_warning_code_is_accepted_for_generic_display", async () => {
    await expectValid(text({ warnings: [{ code: "future_warning_code", page: null }] }));
  });

  it("test_unknown_removed_reason_is_accepted_for_generic_display", async () => {
    await expectValid(text({ removed: [{ reason: "future_reason", count: 1, sample: "x" }] }));
  });
});

describe("AC1 — every field is required", () => {
  it.each(["kind", "bytes", "language", "pages", "blocks", "ocr_pages", "removed", "warnings"])(
    "test_missing_%s_is_unknown_error",
    async (key) => {
      await expectInvalid(without(pdf(), key));
    },
  );

  it("test_stage_2_body_without_extraction_is_unknown_error", async () => {
    await expectInvalid({ kind: "text", bytes: FILE_SIZE });
  });

  it.each(["text", "part", "page"])("test_block_without_%s_is_unknown_error", async (key) => {
    const block = without({ text: "A.", part: "body", page: 1 }, key);
    await expectInvalid(pdf({ blocks: [block] }));
  });

  it.each(["reason", "count", "sample"])(
    "test_removed_without_%s_is_unknown_error",
    async (key) => {
      const item = without({ reason: "same_color", count: 1, sample: "x" }, key);
      await expectInvalid(text({ removed: [item] }));
    },
  );

  it.each(["code", "page"])("test_warning_without_%s_is_unknown_error", async (key) => {
    const item = without({ code: "borderline_text", page: null }, key);
    await expectInvalid(text({ warnings: [item] }));
  });
});

describe("AC1 — unknown fields are rejected (extra=forbid)", () => {
  it("test_extra_top_level_field_is_unknown_error", async () => {
    await expectInvalid(text({ message: "server text" }));
  });

  it("test_extra_block_field_is_unknown_error", async () => {
    await expectInvalid(
      text({ blocks: [{ text: "A.", part: "body", page: null, html: "<b>A</b>" }] }),
    );
  });

  it("test_extra_removed_field_is_unknown_error", async () => {
    await expectInvalid(
      text({ removed: [{ reason: "same_color", count: 1, sample: "x", extra: 1 }] }),
    );
  });

  it("test_extra_warning_field_is_unknown_error", async () => {
    await expectInvalid(text({ warnings: [{ code: "borderline_text", page: null, text: "x" }] }));
  });

  it("test_proto_key_in_body_is_unknown_error", async () => {
    const raw = JSON.stringify(text()).replace(/^\{/, '{"__proto__":{"kind":"pdf"},');
    const response = new Response(raw, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await extractWith(response), "unknown_error");
  });
});

describe("AC1 — wrong values and enums", () => {
  it.each([["de"], ["EN"], [""], [null], [1], ["__proto__"]])(
    "test_language_%j_is_unknown_error",
    async (language) => {
      await expectInvalid(text({ language }));
    },
  );

  it.each([[1], [0], ["1"]])("test_text_with_pages_%j_is_unknown_error", async (pages) => {
    await expectInvalid(text({ pages }));
  });

  it("test_docx_with_pages_is_unknown_error", async () => {
    await expectInvalid(docx({ pages: 2 }));
  });

  it.each([[null], [0], [-1], [1.5], ["1"]])(
    "test_pdf_with_pages_%j_is_unknown_error",
    async (pages) => {
      await expectInvalid(pdf({ pages }));
    },
  );

  it.each([[null], ["x"], [{}], [[null]], [["A."]]])(
    "test_blocks_%j_is_unknown_error",
    async (blocks) => {
      await expectInvalid(text({ blocks }));
    },
  );

  it.each([[null], [1], [["A."]], [{ value: "A." }]])(
    "test_block_text_%j_is_unknown_error",
    async (blockText) => {
      await expectInvalid(text({ blocks: [{ text: blockText, part: "body", page: null }] }));
    },
  );

  it.each([["Body"], ["comment"], [""], [null], ["__proto__"], ["toString"]])(
    "test_block_part_%j_is_unknown_error",
    async (part) => {
      await expectInvalid(text({ blocks: [{ text: "A.", part, page: null }] }));
    },
  );

  it("test_text_block_with_page_is_unknown_error", async () => {
    await expectInvalid(text({ blocks: [{ text: "A.", part: "body", page: 1 }] }));
  });

  it.each([[null], [0], [-1], [1.5], ["1"], [3]])(
    "test_pdf_block_page_%j_with_two_pages_is_unknown_error",
    async (page) => {
      await expectInvalid(pdf({ pages: 2, blocks: [{ text: "A.", part: "body", page }] }));
    },
  );

  it.each([[null], ["2"], [{}]])("test_ocr_pages_%j_is_unknown_error", async (ocr) => {
    await expectInvalid(pdf({ ocr_pages: ocr }));
  });

  it.each([[[0]], [[3]], [[1.5]], [["1"]], [[null]]])(
    "test_pdf_ocr_pages_%j_with_two_pages_is_unknown_error",
    async (ocr) => {
      await expectInvalid(pdf({ pages: 2, ocr_pages: ocr }));
    },
  );

  it.each(["text", "docx"] as const)(
    "test_%s_with_non_empty_ocr_pages_is_unknown_error",
    async (kind) => {
      await expectInvalid(stage3Body(kind, FILE_SIZE, { ocr_pages: [1] }));
    },
  );

  it.each([[null], [{}], ["x"]])("test_removed_%j_is_unknown_error", async (removed) => {
    await expectInvalid(text({ removed }));
  });

  it.each([[0], [-1], [1.5], ["4"], [null]])(
    "test_removed_count_%j_is_unknown_error",
    async (count) => {
      await expectInvalid(text({ removed: [{ reason: "same_color", count, sample: "x" }] }));
    },
  );

  it.each([[null], [1], [""]])("test_removed_reason_%j_is_unknown_error", async (reason) => {
    await expectInvalid(text({ removed: [{ reason, count: 1, sample: "x" }] }));
  });

  it.each([[null], [1], [["x"]]])("test_removed_sample_%j_is_unknown_error", async (sample) => {
    await expectInvalid(text({ removed: [{ reason: "same_color", count: 1, sample }] }));
  });

  it("test_removed_sample_of_200_characters_is_accepted", async () => {
    await expectValid(
      text({ removed: [{ reason: "same_color", count: 1, sample: "s".repeat(200) }] }),
    );
  });

  it("test_removed_sample_above_200_characters_is_unknown_error", async () => {
    await expectInvalid(
      text({ removed: [{ reason: "same_color", count: 1, sample: "s".repeat(201) }] }),
    );
  });

  it.each([[null], [{}], ["x"]])("test_warnings_%j_is_unknown_error", async (warnings) => {
    await expectInvalid(text({ warnings }));
  });

  it.each([[null], [1], [""], [["x"]]])("test_warning_code_%j_is_unknown_error", async (code) => {
    await expectInvalid(text({ warnings: [{ code, page: null }] }));
  });

  it.each([[0], [-1], [1.5], ["2"]])("test_warning_page_%j_is_unknown_error", async (page) => {
    await expectInvalid(pdf({ pages: 3, warnings: [{ code: "borderline_text", page }] }));
  });

  it("test_invalid_body_result_carries_no_server_text", async () => {
    const secret = "SERVER-TEXT-CANARY-7f3a";
    const result = await extractWith(
      jsonResponse(
        200,
        text({ language: "xx", blocks: [{ text: secret, part: "body", page: null }] }),
      ),
    );
    expect(JSON.stringify(result)).not.toContain(secret);
  });
});

describe("AC1 — caps fail closed", () => {
  it("test_20000_blocks_are_accepted", async () => {
    const blocks = Array.from({ length: 20_000 }, () => ({ text: "a", part: "body", page: null }));
    const result = await extractWith(jsonResponse(200, text({ blocks })));
    expect(result.ok).toBe(true);
  });

  it("test_20001_blocks_are_unknown_error", async () => {
    const blocks = Array.from({ length: 20_001 }, () => ({ text: "a", part: "body", page: null }));
    await expectInvalid(text({ blocks }));
  });

  it("test_1000000_characters_are_accepted", async () => {
    const blocks = Array.from({ length: 4 }, () => ({
      text: "a".repeat(250_000),
      part: "body",
      page: null,
    }));
    const result = await extractWith(jsonResponse(200, text({ blocks })));
    expect(result.ok).toBe(true);
  });

  it("test_1000001_characters_are_unknown_error", async () => {
    const blocks = [
      ...Array.from({ length: 4 }, () => ({ text: "a".repeat(250_000), part: "body", page: null })),
      { text: "b", part: "body", page: null },
    ];
    await expectInvalid(text({ blocks }));
  });
});

describe("AC1 — body size caps: 200 up to 4 MiB + 64 KiB, errors 4 KiB", () => {
  const SUCCESS_CAP = 4 * 1024 * 1024 + 64 * 1024;
  const ERROR_CAP = 4 * 1024;
  const CHUNK = 64 * 1024;

  function lazyStream(bytes: Uint8Array): {
    stream: ReadableStream<Uint8Array>;
    pulled: () => number;
  } {
    let offset = 0;
    const stream = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          if (offset >= bytes.length) {
            controller.close();
            return;
          }
          const chunk = bytes.slice(offset, offset + CHUNK);
          offset += chunk.length;
          controller.enqueue(chunk);
        },
      },
      { highWaterMark: 0 },
    );
    return { stream, pulled: () => offset };
  }

  function response(status: number, bytes: Uint8Array, headers: Record<string, string> = {}) {
    const body = lazyStream(bytes);
    return {
      pulled: body.pulled,
      response: new Response(body.stream, {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      }),
    };
  }

  const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));

  it("test_200_body_above_4_kib_is_accepted", async () => {
    const body = text({ blocks: [{ text: "a".repeat(100 * 1024), part: "body", page: null }] });
    const bytes = encode(body);
    const { response: r } = response(200, bytes, { "Content-Length": String(bytes.length) });
    expect(await extractWith(r)).toEqual(okResult("text", FILE_SIZE, body));
  });

  it("test_200_body_of_3_mb_with_1000000_characters_is_accepted", async () => {
    // "€" is one character and three UTF-8 bytes.
    const blocks = Array.from({ length: 4 }, () => ({
      text: "€".repeat(250_000),
      part: "body",
      page: null,
    }));
    const bytes = encode(text({ blocks }));
    expect(bytes.length).toBeGreaterThan(3_000_000);
    const { response: r } = response(200, bytes);
    expect((await extractWith(r)).ok).toBe(true);
  });

  it("test_200_content_length_above_success_cap_is_unknown_error_without_reading", async () => {
    const { response: r, pulled } = response(200, encode(text()), {
      "Content-Length": String(SUCCESS_CAP + 1),
    });
    expectError(await extractWith(r), "unknown_error");
    expect(pulled()).toBe(0);
  });

  it("test_200_streamed_body_above_success_cap_is_unknown_error_and_stops_reading", async () => {
    const head = JSON.stringify(text()).slice(0, -1) + ',"pad":"';
    const bytes = new TextEncoder().encode(head + "a".repeat(SUCCESS_CAP) + '"}');
    const { response: r, pulled } = response(200, bytes);
    expectError(await extractWith(r), "unknown_error");
    const after = pulled();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(after).toBeLessThanOrEqual(SUCCESS_CAP + CHUNK);
    expect(pulled()).toBe(after);
  });

  it("test_422_body_just_above_4_kib_is_unknown_error", async () => {
    const bytes = encode({ error: "empty_file", pad: "a".repeat(ERROR_CAP) });
    const { response: r } = response(422, bytes);
    expectError(await extractWith(r), "unknown_error");
  });

  it("test_501_body_above_4_kib_is_unknown_error", async () => {
    const bytes = encode({ error: "not_implemented", pad: "a".repeat(ERROR_CAP) });
    const { response: r } = response(501, bytes);
    expectError(await extractWith(r), "unknown_error");
  });

  it("test_422_content_length_above_4_kib_is_unknown_error_without_reading", async () => {
    const { response: r, pulled } = response(422, encode({ error: "empty_file" }), {
      "Content-Length": String(ERROR_CAP + 1),
    });
    expectError(await extractWith(r), "unknown_error");
    expect(pulled()).toBe(0);
  });
});

describe("AC1 — 501 not_implemented (temporary)", () => {
  it("test_501_not_implemented_maps_to_not_implemented", async () => {
    expectError(
      await extractWith(jsonResponse(501, { error: "not_implemented" })),
      "not_implemented",
    );
  });

  it.each([
    [422, "not_implemented"],
    [200, "not_implemented"],
    [503, "not_implemented"],
    [501, "busy"],
    [501, "something_else"],
  ])("test_status_%i_with_error_%s_is_unknown_error", async (status, code) => {
    expectError(await extractWith(jsonResponse(status, { error: code })), "unknown_error");
  });
});
