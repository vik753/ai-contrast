/**
 * S3-T6b items 3 and 7 — `extractGoogleDoc` (src/api/googleDoc.ts).
 * Covers the request shape, strict response validation (same rules as
 * `extractFile`), the status/code pairs of S3-T6a item 6, abort and timeout.
 * Threats: T1 (server text never returned), T7 (ID only in the JSON body).
 *
 * Assumptions for the developer: there is no local file, so `bytes` of a `200`
 * body must be a positive safe integer of at most 10 MiB (MAX_FILE_BYTES);
 * the server detects DOCX by magic bytes, so `kind` must be `docx` (any other
 * kind is `unknown_error`).
 *
 * Every test injects `fetchImpl`; no real network call is made.
 * These tests fail until `src/api/googleDoc.ts` exists.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_BLOCKS, MAX_RESPONSE_BYTES, MAX_SUCCESS_RESPONSE_BYTES } from "./extract";
import type { ExtractResult } from "./extract";
import { GOOGLE_DOC_URL, extractGoogleDoc } from "./googleDoc";
import {
  FakeFetch,
  busyResponse,
  jsonResponse,
  okResponse,
  okResult,
  stage3Body,
} from "../test/upload-fakes";

const ID = "1AbCdEfGhIjKlMnOpQrStUvWx_-9";
const BYTES = 2048;

afterEach(() => {
  vi.useRealTimers();
});

function fetchReturning(response: Response | (() => Response)): FakeFetch {
  const fake = new FakeFetch();
  fake.autoRespond = () => (typeof response === "function" ? response() : response);
  return fake;
}

function callWith(response: Response): Promise<ExtractResult> {
  const fake = fetchReturning(response);
  return extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
}

function expectError(result: ExtractResult, code: string): void {
  expect(result.ok).toBe(false);
  if (!result.ok) {
    expect(result.code).toBe(code);
  }
}

describe("request", () => {
  it("test_url_constant_is_the_google_doc_endpoint", () => {
    expect(GOOGLE_DOC_URL).toBe("/api/extract/google-doc");
  });

  it("test_request_goes_to_the_endpoint_without_the_id_in_the_url", async () => {
    const fake = fetchReturning(() => okResponse("docx", BYTES));
    await extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]?.input).toBe("/api/extract/google-doc");
  });

  it("test_request_options_are_post_omit_credentials_no_store_error_redirect", async () => {
    const fake = fetchReturning(() => okResponse("docx", BYTES));
    await extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
    const init = fake.calls[0]?.init;
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("omit");
    expect(init?.redirect).toBe("error");
    expect(init?.cache).toBe("no-store");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("test_request_sets_only_the_json_content_type_header", async () => {
    const fake = fetchReturning(() => okResponse("docx", BYTES));
    await extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
    const headers = new Headers(fake.calls[0]?.init?.headers);
    expect([...headers.entries()]).toEqual([["content-type", "application/json"]]);
  });

  it("test_request_body_is_exactly_the_document_id_json", async () => {
    const fake = fetchReturning(() => okResponse("docx", BYTES));
    await extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
    const body = fake.calls[0]?.body;
    expect(typeof body).toBe("string");
    expect(JSON.parse(body as string)).toEqual({ document_id: ID });
    expect(Object.keys(JSON.parse(body as string) as object)).toEqual(["document_id"]);
  });

  it("test_extract_reads_global_fetch_at_call_time", async () => {
    const fake = fetchReturning(() => okResponse("docx", BYTES));
    vi.stubGlobal("fetch", fake.fetch);
    try {
      expect(await extractGoogleDoc(ID)).toEqual(okResult("docx", BYTES));
    } finally {
      vi.unstubAllGlobals();
    }
    expect(fake.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("successful response", () => {
  it("test_200_with_valid_docx_body_is_ok", async () => {
    expect(await callWith(okResponse("docx", BYTES))).toEqual(okResult("docx", BYTES));
  });

  it("test_200_keeps_blocks_language_and_warnings", async () => {
    const overrides = {
      language: "uk",
      blocks: [
        { text: "Пункт 1", part: "body", page: null },
        { text: "Нижній колонтитул", part: "footer", page: null },
      ],
      warnings: [{ code: "not_read_comments", page: null }],
    };
    expect(await callWith(okResponse("docx", BYTES, overrides))).toEqual(
      okResult("docx", BYTES, overrides),
    );
  });

  it.each(["pdf", "text"] as const)("test_200_with_kind_%s_is_unknown_error", async (kind) => {
    expectError(await callWith(okResponse(kind, BYTES)), "unknown_error");
  });

  it.each([[0], [-1], [5.5], ["5"], [null], [10 * 1024 * 1024 + 1], [Number.MAX_SAFE_INTEGER + 1]])(
    "test_200_with_bytes_%j_is_unknown_error",
    async (bytes) => {
      expectError(
        await callWith(jsonResponse(200, stage3Body("docx", 1, { bytes }))),
        "unknown_error",
      );
    },
  );

  it("test_200_with_unknown_top_level_field_is_unknown_error", async () => {
    expectError(await callWith(okResponse("docx", BYTES, { extra: 1 })), "unknown_error");
  });

  it.each(["kind", "bytes", "language", "pages", "blocks", "ocr_pages", "removed", "warnings"])(
    "test_200_without_%s_is_unknown_error",
    async (key) => {
      const body = Object.fromEntries(
        Object.entries(stage3Body("docx", BYTES)).filter(([name]) => name !== key),
      );
      expectError(await callWith(jsonResponse(200, body)), "unknown_error");
    },
  );

  it("test_200_with_unknown_block_field_is_unknown_error", async () => {
    const blocks = [{ text: "x", part: "body", page: null, html: "<b>" }];
    expectError(await callWith(okResponse("docx", BYTES, { blocks })), "unknown_error");
  });

  it("test_200_with_unknown_block_part_is_unknown_error", async () => {
    const blocks = [{ text: "x", part: "script", page: null }];
    expectError(await callWith(okResponse("docx", BYTES, { blocks })), "unknown_error");
  });

  it("test_200_with_pages_for_docx_is_unknown_error", async () => {
    expectError(await callWith(okResponse("docx", BYTES, { pages: 3 })), "unknown_error");
  });

  it("test_200_with_page_number_in_docx_block_is_unknown_error", async () => {
    const blocks = [{ text: "x", part: "body", page: 1 }];
    expectError(await callWith(okResponse("docx", BYTES, { blocks })), "unknown_error");
  });

  it("test_200_with_unknown_language_value_is_unknown_error", async () => {
    expectError(await callWith(okResponse("docx", BYTES, { language: "de" })), "unknown_error");
  });

  it("test_200_with_more_than_max_blocks_is_unknown_error", async () => {
    const blocks = Array.from({ length: MAX_BLOCKS + 1 }, () => ({
      text: "a",
      part: "body",
      page: null,
    }));
    expectError(await callWith(okResponse("docx", BYTES, { blocks })), "unknown_error");
  });

  it("test_200_with_more_than_a_million_chars_is_unknown_error", async () => {
    const blocks = [{ text: "a".repeat(1_000_001), part: "body", page: null }];
    expectError(await callWith(okResponse("docx", BYTES, { blocks })), "unknown_error");
  });

  it("test_200_array_body_is_unknown_error", async () => {
    expectError(await callWith(jsonResponse(200, [])), "unknown_error");
  });

  it("test_200_not_json_content_type_is_unknown_error", async () => {
    const response = new Response(JSON.stringify(stage3Body("docx", BYTES)), {
      status: 200,
      headers: { "Content-Type": "text/html" },
    });
    expectError(await callWith(response), "unknown_error");
  });

  it("test_200_with_invalid_json_is_unknown_error", async () => {
    const response = new Response("{not json", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await callWith(response), "unknown_error");
  });

  it("test_200_with_declared_length_above_cap_is_unknown_error", async () => {
    const response = new Response("{}", {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Content-Length": String(MAX_SUCCESS_RESPONSE_BYTES + 1),
      },
    });
    expectError(await callWith(response), "unknown_error");
  });

  it("test_200_streamed_above_cap_is_unknown_error", async () => {
    const chunk = new Uint8Array(1024 * 1024).fill(32);
    let sent = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent > MAX_SUCCESS_RESPONSE_BYTES) {
          controller.close();
          return;
        }
        sent += chunk.byteLength;
        controller.enqueue(chunk);
      },
    });
    const response = new Response(stream, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await callWith(response), "unknown_error");
  });

  it("test_error_body_above_4_kib_is_unknown_error", async () => {
    const padding = "x".repeat(MAX_RESPONSE_BYTES);
    const response = new Response(JSON.stringify({ error: "google_doc_not_found", padding }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await callWith(response), "unknown_error");
  });
});

/** [code, status] pairs of S3-T6a item 6 and the shared codes. */
const NEW_CODES: readonly (readonly [string, number])[] = [
  ["invalid_request", 422],
  ["invalid_google_doc_id", 422],
  ["google_doc_not_public", 422],
  ["google_doc_not_found", 422],
  ["google_doc_too_large", 422],
  ["google_doc_unavailable", 502],
  ["google_doc_timeout", 504],
  ["request_too_large", 413],
  ["unsupported_media_type", 415],
  ["busy", 503],
  ["extraction_failed", 422],
  ["extraction_timeout", 422],
  ["too_many_pages", 422],
  ["too_much_text", 422],
  ["encrypted_unsupported", 422],
  ["no_text_extracted", 422],
  ["suspicious_package", 422],
  ["archive_rejected", 422],
  ["docx_strict_unsupported", 422],
];

describe("error codes", () => {
  it.each(NEW_CODES)("test_code_%s_with_status_%i_is_returned", async (code, status) => {
    const result = await callWith(jsonResponse(status, { error: code }));
    expectError(result, code);
  });

  const ALL_STATUSES = [400, 408, 411, 413, 415, 422, 500, 501, 502, 503, 504];
  const GOOGLE_ONLY = NEW_CODES.filter(
    ([code]) =>
      code.startsWith("google_doc_") ||
      code === "invalid_request" ||
      code === "invalid_google_doc_id",
  );

  it.each(
    GOOGLE_ONLY.flatMap(([code, status]) =>
      ALL_STATUSES.filter((other) => other !== status).map((other) => [code, other] as const),
    ),
  )("test_code_%s_with_wrong_status_%i_is_unknown_error", async (code, status) => {
    expectError(await callWith(jsonResponse(status, { error: code })), "unknown_error");
  });

  it.each(["", "other_error", "__proto__", "toString", "GOOGLE_DOC_NOT_FOUND"])(
    "test_unknown_code_%j_is_unknown_error",
    async (code) => {
      expectError(await callWith(jsonResponse(422, { error: code })), "unknown_error");
    },
  );

  it("test_error_body_with_non_string_code_is_unknown_error", async () => {
    expectError(await callWith(jsonResponse(422, { error: 5 })), "unknown_error");
  });

  it("test_server_text_in_error_body_is_never_returned", async () => {
    const result = await callWith(
      jsonResponse(422, { error: "google_doc_not_found", detail: "SERVER-TEXT-CANARY" }),
    );
    expect(JSON.stringify(result)).not.toContain("SERVER-TEXT-CANARY");
  });

  it("test_busy_returns_retry_after_seconds", async () => {
    expect(await callWith(busyResponse("7"))).toEqual({
      ok: false,
      code: "busy",
      retryAfterSeconds: 7,
    });
  });

  it("test_busy_without_retry_after_has_no_delay", async () => {
    expect(await callWith(busyResponse(null))).toEqual({ ok: false, code: "busy" });
  });
});

describe("network, abort and timeout", () => {
  it("test_fetch_rejection_returns_network_error_and_does_not_throw", async () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    const result = await extractGoogleDoc(ID, { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(result).toEqual({ ok: false, code: "network_error" });
  });

  it("test_fetch_throwing_synchronously_returns_network_error", async () => {
    const fetchImpl = vi.fn(() => {
      throw new Error("boom");
    });
    const result = await extractGoogleDoc(ID, { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(result).toEqual({ ok: false, code: "network_error" });
  });

  it("test_network_error_result_does_not_contain_the_id", async () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError(`failed ${ID}`)));
    const result = await extractGoogleDoc(ID, { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(JSON.stringify(result)).not.toContain(ID);
  });

  it("test_already_aborted_signal_returns_aborted_without_a_request", async () => {
    const fake = new FakeFetch();
    const controller = new AbortController();
    controller.abort();
    const result = await extractGoogleDoc(ID, {
      fetchImpl: fake.asFetch(),
      signal: controller.signal,
    });
    expect(result).toEqual({ ok: false, code: "aborted" });
    expect(fake.fetch).not.toHaveBeenCalled();
  });

  it("test_abort_during_request_aborts_fetch_and_returns_aborted", async () => {
    const fake = new FakeFetch();
    const controller = new AbortController();
    const pending = extractGoogleDoc(ID, { fetchImpl: fake.asFetch(), signal: controller.signal });
    expect(fake.calls).toHaveLength(1);
    controller.abort();
    expect(fake.calls[0]?.signal?.aborted).toBe(true);
    expect(await pending).toEqual({ ok: false, code: "aborted" });
  });

  it("test_timeout_option_returns_timeout", async () => {
    vi.useFakeTimers();
    const fake = new FakeFetch();
    const pending = extractGoogleDoc(ID, { fetchImpl: fake.asFetch(), timeoutMs: 1_000 });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fake.calls[0]?.signal?.aborted).toBe(true);
    expect(await pending).toEqual({ ok: false, code: "timeout" });
  });

  it("test_default_timeout_is_60_seconds", async () => {
    vi.useFakeTimers();
    const fake = new FakeFetch();
    const pending = extractGoogleDoc(ID, { fetchImpl: fake.asFetch() });
    await vi.advanceTimersByTimeAsync(59_999);
    expect(fake.calls[0]?.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ ok: false, code: "timeout" });
  });

  it("test_timeout_covers_a_stalled_response_body", async () => {
    vi.useFakeTimers();
    const fake = new FakeFetch();
    fake.autoRespond = () => {
      const stream = new ReadableStream<Uint8Array>({ start: () => undefined });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    const pending = extractGoogleDoc(ID, { fetchImpl: fake.asFetch(), timeoutMs: 500 });
    await vi.advanceTimersByTimeAsync(500);
    expect(await pending).toEqual({ ok: false, code: "timeout" });
  });
});
