/**
 * S3-T4 (developer tests): stage 3 `422` extraction codes pass the
 * status-paired allowlist; code points are counted like the server does.
 */
import { describe, expect, it } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { FakeFetch, jsonResponse, makeFile, stage3Body } from "../test/upload-fakes";
import { extractFile, type ExtractResult } from "./extract";

const STAGE3_CODES = [
  "extraction_failed",
  "extraction_timeout",
  "too_many_pages",
  "too_much_text",
  "encrypted_unsupported",
  "no_text_extracted",
  "text_decoding_failed",
  "suspicious_package",
  "docx_strict_unsupported",
  "pdf_damaged",
] as const;

async function extractWith(response: Response): Promise<ExtractResult> {
  const fake = new FakeFetch();
  fake.autoRespond = () => response;
  return extractFile(makeFile("a.bin", { content: "12345" }), { fetchImpl: fake.asFetch() });
}

describe("stage 3 error codes", () => {
  it.each(STAGE3_CODES)("test_422_%s_maps_to_same_code", async (code) => {
    expect(await extractWith(jsonResponse(422, { error: code }))).toEqual({ ok: false, code });
  });

  it.each(STAGE3_CODES)("test_400_%s_is_unknown_error", async (code) => {
    expect(await extractWith(jsonResponse(400, { error: code }))).toEqual({
      ok: false,
      code: "unknown_error",
    });
  });

  it.each(STAGE3_CODES)("test_%s_has_a_message_in_en_uk_ru", (code) => {
    const messages = [enJson, ukJson, ruJson].map((locale) => locale.upload.errors[code]);
    for (const message of messages) {
      expect(message.length).toBeGreaterThan(20);
    }
    expect(new Set(messages).size).toBe(3);
  });
});

describe("character cap counts code points", () => {
  it("test_1000000_non_bmp_characters_are_accepted", async () => {
    // "😀" is one character (two UTF-16 units).
    const blocks = Array.from({ length: 4 }, () => ({
      text: "😀".repeat(250_000),
      part: "body",
      page: null,
    }));
    const result = await extractWith(jsonResponse(200, stage3Body("text", 5, { blocks })));
    expect(result.ok).toBe(true);
  });

  it("test_1000001_non_bmp_characters_are_unknown_error", async () => {
    const blocks = [
      ...Array.from({ length: 4 }, () => ({
        text: "😀".repeat(250_000),
        part: "body",
        page: null,
      })),
      { text: "😀", part: "body", page: null },
    ];
    const result = await extractWith(jsonResponse(200, stage3Body("text", 5, { blocks })));
    expect(result).toEqual({ ok: false, code: "unknown_error" });
  });

  it("test_sample_of_200_non_bmp_characters_is_accepted", async () => {
    const removed = [{ reason: "same_color", count: 1, sample: "😀".repeat(200) }];
    const result = await extractWith(jsonResponse(200, stage3Body("text", 5, { removed })));
    expect(result.ok).toBe(true);
  });

  it.each(["Same_color", "1abc", "a-b", "x".repeat(65)])(
    "test_reason_%s_outside_code_pattern_is_unknown_error",
    async (reason) => {
      const removed = [{ reason, count: 1, sample: "x" }];
      const result = await extractWith(jsonResponse(200, stage3Body("text", 5, { removed })));
      expect(result).toEqual({ ok: false, code: "unknown_error" });
    },
  );

  it("test_docx_warning_with_page_is_unknown_error", async () => {
    const warnings = [{ code: "not_read_object", page: 1 }];
    const result = await extractWith(jsonResponse(200, stage3Body("docx", 5, { warnings })));
    expect(result).toEqual({ ok: false, code: "unknown_error" });
  });
});
