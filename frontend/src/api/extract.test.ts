/**
 * S2-T2 — `extractFile` (src/api/extract.ts).
 * Covers AC4 (timeout, network error, busy), AC5 (request privacy) and
 * AC6 (response handling). Threats: T1 (server text never shown), T3, T11
 * (file names never leave the browser).
 *
 * Every test injects `fetchImpl`; no real network call is made.
 * These tests fail until `src/api/extract.ts` exists.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { extractFile, type ExtractErrorCode, type ExtractResult } from "./extract";
import {
  FakeFetch,
  busyResponse,
  canary,
  jsonResponse,
  makeFile,
  okResponse,
} from "../test/upload-fakes";

afterEach(() => {
  vi.useRealTimers();
});

function fetchReturning(response: Response | (() => Response)): FakeFetch {
  const fake = new FakeFetch();
  fake.autoRespond = () => (typeof response === "function" ? response() : response);
  return fake;
}

async function extractWith(response: Response, file: Blob = makeFile("a.pdf")) {
  const fake = fetchReturning(response);
  return extractFile(file, { fetchImpl: fake.asFetch() });
}

function expectError(result: ExtractResult, code: ExtractErrorCode): void {
  expect(result.ok).toBe(false);
  if (!result.ok) {
    expect(result.code).toBe(code);
  }
}

describe("AC6 — successful response", () => {
  it.each(["pdf", "docx", "text"] as const)(
    "test_200_with_kind_%s_and_matching_bytes_is_ok",
    async (kind) => {
      const file = makeFile("a.bin", { content: "0123456789" });
      const result = await extractWith(okResponse(kind, file.size), file);
      expect(result).toEqual({ ok: true, kind, bytes: file.size });
    },
  );

  it("test_200_with_unknown_kind_is_unknown_error", async () => {
    const file = makeFile("a.exe");
    expectError(await extractWith(okResponse("exe" as "pdf", file.size), file), "unknown_error");
  });

  it.each(["PDF", "", "__proto__", "toString"])(
    "test_200_with_kind_%j_outside_allowlist_is_unknown_error",
    async (kind) => {
      const file = makeFile("a.pdf");
      expectError(
        await extractWith(jsonResponse(200, { kind, bytes: file.size }), file),
        "unknown_error",
      );
    },
  );

  it("test_200_with_bytes_different_from_blob_size_is_unknown_error", async () => {
    const file = makeFile("a.pdf", { content: "12345" });
    expectError(await extractWith(okResponse("pdf", file.size + 1), file), "unknown_error");
  });

  it.each([["5"], [null], [5.5], [-5]])(
    "test_200_with_bytes_%j_of_wrong_type_or_value_is_unknown_error",
    async (bytes) => {
      const file = makeFile("a.pdf", { content: "12345" });
      expectError(
        await extractWith(jsonResponse(200, { kind: "pdf", bytes }), file),
        "unknown_error",
      );
    },
  );

  it("test_200_without_bytes_is_unknown_error", async () => {
    expectError(await extractWith(jsonResponse(200, { kind: "pdf" })), "unknown_error");
  });

  it.each([[null], [[]], ["pdf"], [42]])(
    "test_200_with_json_%j_that_is_not_an_object_is_unknown_error",
    async (body) => {
      expectError(await extractWith(jsonResponse(200, body)), "unknown_error");
    },
  );

  it("test_200_with_error_body_is_unknown_error", async () => {
    expectError(await extractWith(jsonResponse(200, { error: "busy" })), "unknown_error");
  });

  it("test_200_with_malformed_json_is_unknown_error", async () => {
    const response = new Response('{"kind": "pdf", "bytes":', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await extractWith(response), "unknown_error");
  });

  it("test_200_with_non_json_body_is_unknown_error", async () => {
    const response = new Response("<html>ok</html>", {
      status: 200,
      headers: { "Content-Type": "text/html" },
    });
    expectError(await extractWith(response), "unknown_error");
  });
});

describe("AC6 — error codes from the server are mapped through an allowlist", () => {
  const SERVER_ERRORS: [number, ExtractErrorCode][] = [
    [411, "length_required"],
    [413, "file_too_large"],
    [413, "request_too_large"],
    [415, "unsupported_media_type"],
    [422, "empty_file"],
    [422, "unsupported_type"],
    [422, "legacy_office_unsupported"],
    [422, "pages_unsupported"],
    [422, "archive_rejected"],
    [503, "busy"],
    // Review round 1 (PR #15 contract).
    [400, "length_mismatch"],
    [408, "upload_timeout"],
  ];

  // Review round 1: a server code counts only together with its status.
  const MISMATCHED: [number, string][] = [
    [422, "busy"],
    [503, "empty_file"],
    [400, "upload_timeout"],
    [408, "length_mismatch"],
    [413, "unsupported_type"],
    [422, "file_too_large"],
    [500, "busy"],
    [400, "archive_rejected"],
    [411, "unsupported_media_type"],
    [415, "length_required"],
  ];

  it.each(MISMATCHED)(
    "test_status_%i_with_mismatched_error_%s_maps_to_unknown_error",
    async (status, code) => {
      expectError(
        await extractWith(jsonResponse(status, { error: code }, { "Retry-After": "5" })),
        "unknown_error",
      );
    },
  );

  it.each(SERVER_ERRORS)("test_status_%i_with_error_%s_maps_to_same_code", async (status, code) => {
    expectError(await extractWith(jsonResponse(status, { error: code })), code);
  });

  it.each([
    "something_new",
    "",
    "__proto__",
    "constructor",
    "toString",
    "BUSY",
    "<script>alert(1)</script>",
  ])("test_unknown_error_code_%j_maps_to_unknown_error", async (code) => {
    expectError(await extractWith(jsonResponse(422, { error: code })), "unknown_error");
  });

  it.each(["network_error", "timeout", "aborted", "unknown_error"])(
    "test_client_only_code_%s_sent_by_server_maps_to_unknown_error",
    async (code) => {
      // Assumption: only server codes are accepted from a server body.
      const result = await extractWith(jsonResponse(422, { error: code }));
      expectError(result, "unknown_error");
    },
  );

  it.each([
    [{ error: 42 }],
    [{ error: null }],
    [{ error: ["busy"] }],
    [{ detail: "busy" }],
    [[]],
    ["busy"],
  ])("test_error_body_%j_without_string_code_maps_to_unknown_error", async (body) => {
    expectError(await extractWith(jsonResponse(422, body)), "unknown_error");
  });

  it("test_500_with_non_json_body_maps_to_unknown_error", async () => {
    const response = new Response("Internal Server Error", { status: 500 });
    expectError(await extractWith(response), "unknown_error");
  });

  it("test_error_with_malformed_json_maps_to_unknown_error", async () => {
    const response = new Response('{"error": "bu', {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await extractWith(response), "unknown_error");
  });

  it("test_error_result_carries_no_server_text", async () => {
    const secret = canary("SERVER-TEXT");
    const result = await extractWith(
      jsonResponse(422, { error: "unsupported_type", message: secret, detail: secret }),
    );
    expectError(result, "unsupported_type");
    expect(JSON.stringify(result)).not.toContain(secret);
  });

  it("test_unknown_code_text_is_not_copied_into_result", async () => {
    const secret = canary("SERVER-CODE");
    const result = await extractWith(jsonResponse(422, { error: secret }));
    expect(JSON.stringify(result)).not.toContain(secret);
  });
});

describe("AC4 — busy carries Retry-After", () => {
  it("test_busy_returns_retry_after_seconds_from_header", async () => {
    const result = await extractWith(busyResponse("5"));
    expect(result).toEqual({ ok: false, code: "busy", retryAfterSeconds: 5 });
  });

  it("test_busy_with_other_retry_after_value_returns_that_value", async () => {
    const result = await extractWith(busyResponse("2"));
    expect(result).toEqual({ ok: false, code: "busy", retryAfterSeconds: 2 });
  });

  it.each([[null], ["soon"], ["-3"], [""]])(
    "test_busy_with_retry_after_%j_never_returns_invalid_number",
    async (header) => {
      const result = await extractWith(busyResponse(header));
      expectError(result, "busy");
      if (!result.ok && result.retryAfterSeconds !== undefined) {
        expect(Number.isFinite(result.retryAfterSeconds)).toBe(true);
        expect(result.retryAfterSeconds).toBeGreaterThanOrEqual(0);
      }
    },
  );

  it("test_non_busy_error_has_no_retry_after_seconds", async () => {
    const result = await extractWith(
      jsonResponse(422, { error: "empty_file" }, { "Retry-After": "5" }),
    );
    expect(result).toEqual({ ok: false, code: "empty_file" });
  });
});

describe("AC4 — network failure, timeout and abort; it never throws", () => {
  it("test_rejected_fetch_returns_network_error", async () => {
    const fake = new FakeFetch();
    const pending = extractFile(makeFile("a.pdf"), { fetchImpl: fake.asFetch() });
    await vi.waitFor(() => expect(fake.calls).toHaveLength(1));
    fake.calls[0]?.fail(new TypeError("Failed to fetch"));
    expectError(await pending, "network_error");
  });

  it("test_synchronously_throwing_fetch_does_not_throw", async () => {
    const fetchImpl = vi.fn(() => {
      throw new TypeError("boom");
    }) as unknown as typeof fetch;
    const result = await extractFile(makeFile("a.pdf"), { fetchImpl });
    expect(result.ok).toBe(false);
  });

  it("test_body_read_failure_does_not_throw", async () => {
    const broken = new Response(
      new ReadableStream({
        start(controller) {
          controller.error(new TypeError("stream broken"));
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    const result = await extractWith(broken);
    expect(result.ok).toBe(false);
  });

  it("test_custom_timeout_returns_timeout", async () => {
    const fake = new FakeFetch();
    const result = await extractFile(makeFile("a.pdf"), {
      fetchImpl: fake.asFetch(),
      timeoutMs: 20,
    });
    expectError(result, "timeout");
    expect(fake.calls[0]?.signal?.aborted).toBe(true);
  });

  it("test_default_timeout_is_60_seconds", async () => {
    // Assumption: the timeout uses setTimeout (fakeable), not AbortSignal.timeout.
    vi.useFakeTimers();
    const fake = new FakeFetch();
    let result: ExtractResult | undefined;
    void extractFile(makeFile("a.pdf"), { fetchImpl: fake.asFetch() }).then((r) => {
      result = r;
    });
    await vi.advanceTimersByTimeAsync(59_999);
    expect(result).toBeUndefined();
    await vi.advanceTimersByTimeAsync(1);
    expect(result).toEqual({ ok: false, code: "timeout" });
  });

  it("test_caller_abort_returns_aborted", async () => {
    const fake = new FakeFetch();
    const controller = new AbortController();
    const pending = extractFile(makeFile("a.pdf"), {
      fetchImpl: fake.asFetch(),
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(fake.calls).toHaveLength(1));
    controller.abort();
    expectError(await pending, "aborted");
    expect(fake.calls[0]?.signal?.aborted).toBe(true);
  });

  it("test_already_aborted_signal_returns_aborted", async () => {
    const fake = new FakeFetch();
    const controller = new AbortController();
    controller.abort();
    const result = await extractFile(makeFile("a.pdf"), {
      fetchImpl: fake.asFetch(),
      signal: controller.signal,
    });
    expectError(result, "aborted");
  });

  it("test_fetch_receives_an_abort_signal", async () => {
    const fake = fetchReturning(() => okResponse("pdf", 3));
    await extractFile(makeFile("a.pdf", { content: "abc" }), { fetchImpl: fake.asFetch() });
    expect(fake.calls[0]?.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("AC5 — request privacy (T3, T11)", () => {
  async function sendCanaryFile(type = "application/pdf") {
    const name = `${canary("FILENAME")}.pdf`;
    const file = makeFile(name, { content: "%PDF-1.7 synthetic", type });
    const fake = fetchReturning(() => okResponse("pdf", file.size));
    await extractFile(file, { fetchImpl: fake.asFetch() });
    expect(fake.calls).toHaveLength(1);
    const call = fake.calls[0];
    if (call === undefined) {
      throw new Error("no call");
    }
    return { name, file, call };
  }

  it("test_method_is_post", async () => {
    const { call } = await sendCanaryFile();
    expect(call.init?.method?.toUpperCase()).toBe("POST");
  });

  it("test_url_is_exactly_api_extract", async () => {
    const { call } = await sendCanaryFile();
    expect(call.input).toBe("/api/extract");
  });

  it("test_body_is_the_same_file_object", async () => {
    const { file, call } = await sendCanaryFile();
    expect(call.body).toBe(file);
  });

  it("test_body_is_not_form_data_or_string", async () => {
    const { call } = await sendCanaryFile();
    expect(call.body).not.toBeInstanceOf(FormData);
    expect(typeof call.body).not.toBe("string");
    expect(call.body).toBeInstanceOf(Blob);
  });

  it("test_plain_blob_is_sent_as_is", async () => {
    const blob = new Blob(["hello"]);
    const fake = fetchReturning(() => okResponse("text", blob.size));
    const result = await extractFile(blob, { fetchImpl: fake.asFetch() });
    expect(result).toEqual({ ok: true, kind: "text", bytes: 5 });
    expect(fake.calls[0]?.body).toBe(blob);
  });

  it.each(["application/pdf", "text/plain", ""])(
    "test_only_header_is_octet_stream_content_type_for_file_type_%j",
    async (type) => {
      const { call } = await sendCanaryFile(type);
      const headers = Array.from(new Headers(call.init?.headers).entries());
      expect(headers).toEqual([["content-type", "application/octet-stream"]]);
    },
  );

  it("test_file_name_canary_is_not_in_url_headers_or_init", async () => {
    const { name, call } = await sendCanaryFile();
    const marker = name.slice(0, name.length - ".pdf".length);
    expect(String(call.input)).not.toContain(marker);
    const headers = JSON.stringify(Array.from(new Headers(call.init?.headers).entries()));
    expect(headers).not.toContain(marker);
    const rest: Record<string, unknown> = { ...call.init };
    delete rest.body;
    delete rest.signal;
    expect(JSON.stringify(rest)).not.toContain(marker);
  });

  it("test_file_name_canary_is_not_in_body_bytes", async () => {
    const { name, call } = await sendCanaryFile();
    const marker = name.slice(0, name.length - ".pdf".length);
    const bytes = await (call.body as Blob).text();
    expect(bytes).not.toContain(marker);
  });
});

/**
 * Review round 1 — the response body is read up to 4 KiB; a larger declared
 * or streamed body, or a non-JSON Content-Type, gives `unknown_error`.
 */
describe("Review round 1 — response size cap and Content-Type", () => {
  const CAP = 4 * 1024;
  const CHUNK = 1024;
  const encoder = new TextEncoder();

  interface TrackedBody {
    stream: ReadableStream<Uint8Array>;
    pulled: () => number;
    cancelled: () => boolean;
  }

  /** A lazy stream (highWaterMark 0): bytes are produced only when read. */
  function trackedBody(text: string): TrackedBody {
    const bytes = encoder.encode(text);
    let offset = 0;
    let cancelled = false;
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
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    return { stream, pulled: () => offset, cancelled: () => cancelled };
  }

  /** Valid JSON for a 5-byte file, padded to `size` bytes. */
  function paddedOkJson(size: number): string {
    const head = '{"kind":"pdf","bytes":5,"pad":"';
    const tail = '"}';
    return head + "a".repeat(Math.max(0, size - head.length - tail.length)) + tail;
  }

  const FILE = () => makeFile("a.pdf", { content: "12345" });

  it("test_small_json_body_under_cap_is_accepted", async () => {
    const body = trackedBody(paddedOkJson(CAP - 100));
    const response = new Response(body.stream, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expect(await extractWith(response, FILE())).toEqual({ ok: true, kind: "pdf", bytes: 5 });
  });

  it("test_content_type_with_charset_is_accepted", async () => {
    const response = new Response('{"kind":"pdf","bytes":5}', {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
    expect(await extractWith(response, FILE())).toEqual({ ok: true, kind: "pdf", bytes: 5 });
  });

  it("test_content_length_above_cap_is_unknown_error_without_reading_body", async () => {
    const body = trackedBody('{"kind":"pdf","bytes":5}');
    const response = new Response(body.stream, {
      status: 200,
      headers: { "Content-Type": "application/json", "Content-Length": String(CAP + 1) },
    });
    expectError(await extractWith(response, FILE()), "unknown_error");
    expect(body.pulled()).toBe(0);
  });

  it("test_streamed_body_above_cap_is_unknown_error", async () => {
    const body = trackedBody(paddedOkJson(1024 * 1024));
    const response = new Response(body.stream, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await extractWith(response, FILE()), "unknown_error");
  });

  it("test_streamed_body_above_cap_stops_reading", async () => {
    const body = trackedBody(paddedOkJson(1024 * 1024));
    const response = new Response(body.stream, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    await extractWith(response, FILE());
    const afterResult = body.pulled();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(afterResult).toBeLessThanOrEqual(CAP + CHUNK);
    expect(body.pulled()).toBe(afterResult);
  });

  it("test_streamed_error_body_above_cap_is_unknown_error", async () => {
    const head = '{"error":"empty_file","pad":"';
    const body = trackedBody(head + "a".repeat(64 * 1024) + '"}');
    const response = new Response(body.stream, {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
    expectError(await extractWith(response), "unknown_error");
    expect(body.pulled()).toBeLessThanOrEqual(CAP + CHUNK);
  });

  it.each([
    [200, "text/html", '{"kind":"pdf","bytes":5}'],
    [200, "text/plain", '{"kind":"pdf","bytes":5}'],
    [502, "text/html", "<html><body>Bad Gateway</body></html>"],
    [503, "text/html", '{"error":"busy"}'],
    [422, "application/octet-stream", '{"error":"empty_file"}'],
  ])("test_status_%i_with_content_type_%s_is_unknown_error", async (status, type, text) => {
    const response = new Response(text, { status, headers: { "Content-Type": type } });
    expectError(await extractWith(response, FILE()), "unknown_error");
  });

  it("test_missing_content_type_is_unknown_error", async () => {
    // A byte-array body gets no Content-Type header.
    const response = new Response(encoder.encode('{"kind":"pdf","bytes":5}'), { status: 200 });
    expect(response.headers.get("Content-Type")).toBeNull();
    expectError(await extractWith(response, FILE()), "unknown_error");
  });
});

describe("Review round 1 — request options are pinned (T3)", () => {
  async function sentInit(): Promise<RequestInit> {
    const file = makeFile("a.pdf", { content: "abc" });
    const fake = fetchReturning(() => okResponse("pdf", file.size));
    await extractFile(file, { fetchImpl: fake.asFetch() });
    const init = fake.calls[0]?.init;
    if (init === undefined) {
      throw new Error("fetch was called without options");
    }
    return init;
  }

  it("test_credentials_are_omitted", async () => {
    expect((await sentInit()).credentials).toBe("omit");
  });

  it("test_redirects_are_errors", async () => {
    expect((await sentInit()).redirect).toBe("error");
  });

  it("test_cache_is_no_store", async () => {
    expect((await sentInit()).cache).toBe("no-store");
  });

  it("test_keepalive_is_not_set", async () => {
    const init = await sentInit();
    expect(init.keepalive ?? false).toBe(false);
  });

  it("test_referrer_and_referrer_policy_are_not_overridden", async () => {
    const init = await sentInit();
    expect("referrer" in init).toBe(false);
    expect("referrerPolicy" in init).toBe(false);
  });
});
