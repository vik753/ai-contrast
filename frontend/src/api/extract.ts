/**
 * Client for `POST /api/extract` (stage 2 API contract, ADR 0010).
 *
 * - The body is the file itself (raw bytes). No multipart, no file name in
 *   the URL, the headers or the body (threat model T3, T11).
 * - The only header we set is `Content-Type: application/octet-stream`.
 *   The browser adds `Content-Length` for a `Blob` body.
 * - The response must be `application/json` and at most 4 KiB.
 * - The response is validated strictly. Error codes pass an allowlist;
 *   anything else becomes `unknown_error`. Server text is never returned,
 *   so it can never be shown (threat model T1).
 * - `extractFile` never throws.
 */

export type FileKind = "pdf" | "docx" | "text";

/** Error codes the server may send (stage 2 API contract). */
export type ServerErrorCode =
  | "length_required"
  | "file_too_large"
  | "request_too_large"
  | "unsupported_media_type"
  | "empty_file"
  | "unsupported_type"
  | "legacy_office_unsupported"
  | "pages_unsupported"
  | "archive_rejected"
  | "busy"
  | "length_mismatch"
  | "upload_timeout";

/** Error codes produced in the browser only. */
export type ClientErrorCode = "network_error" | "timeout" | "aborted" | "unknown_error";

export type ExtractErrorCode = ServerErrorCode | ClientErrorCode;

export type ExtractResult =
  | { ok: true; kind: FileKind; bytes: number }
  | { ok: false; code: ExtractErrorCode; retryAfterSeconds?: number };

export interface ExtractOptions {
  /** Aborts the request; the result is then `aborted`. */
  signal?: AbortSignal;
  /** Replaces the global `fetch` (tests). Default: `globalThis.fetch` at call time. */
  fetchImpl?: typeof fetch;
  /** Timeout for the whole request, response body included. Default: 60 s. */
  timeoutMs?: number;
}

export const EXTRACT_URL = "/api/extract";
export const DEFAULT_EXTRACT_TIMEOUT_MS = 60_000;

/** Largest response body we read. Real answers are a few dozen bytes. */
export const MAX_RESPONSE_BYTES = 4 * 1024;

const FILE_KINDS: ReadonlySet<string> = new Set<FileKind>(["pdf", "docx", "text"]);

/**
 * Allowed error codes per HTTP status. A code is accepted only with the
 * status the API contract gives it. `Map` and `Set` lookups never reach
 * `Object.prototype`, so `__proto__` or `toString` cannot match.
 */
const SERVER_ERRORS: ReadonlyMap<number, ReadonlySet<string>> = new Map<
  number,
  ReadonlySet<ServerErrorCode>
>([
  [411, new Set(["length_required"])],
  [413, new Set(["file_too_large", "request_too_large"])],
  [415, new Set(["unsupported_media_type"])],
  [
    422,
    new Set([
      "empty_file",
      "unsupported_type",
      "legacy_office_unsupported",
      "pages_unsupported",
      "archive_rejected",
    ]),
  ],
  [400, new Set(["length_mismatch"])],
  [408, new Set(["upload_timeout"])],
  [503, new Set(["busy"])],
]);

function isServerErrorCode(status: number, code: string): code is ServerErrorCode {
  return SERVER_ERRORS.get(status)?.has(code) === true;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Own property only: inherited names such as `constructor` never count. */
function ownValue(record: Record<string, unknown>, key: string): unknown {
  return Object.hasOwn(record, key) ? record[key] : undefined;
}

/** `Retry-After` in delta-seconds (digits only). HTTP dates are ignored. */
function parseRetryAfter(header: string | null): number | undefined {
  if (header === null || !/^\d{1,6}$/.test(header.trim())) {
    return undefined;
  }
  return Number(header.trim());
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/** `application/json`, parameters allowed (`; charset=utf-8`), case-insensitive. */
function isJson(headers: Headers): boolean {
  const type = headers.get("Content-Type");
  return type?.split(";")[0]?.trim().toLowerCase() === "application/json";
}

/** Marker for a body that is too large or not valid UTF-8. */
const UNREADABLE = Symbol("unreadable");

/**
 * Reads the body as UTF-8 text, at most `MAX_RESPONSE_BYTES`. A larger
 * declared `Content-Length` is rejected before reading; a larger streamed
 * body stops the reading and cancels the stream. Stream errors are thrown.
 */
async function readCapped(response: Response): Promise<string | typeof UNREADABLE> {
  const body = response.body;
  const declared = response.headers.get("Content-Length");
  if (
    declared !== null &&
    (!/^\d+$/.test(declared.trim()) || Number(declared) > MAX_RESPONSE_BYTES)
  ) {
    void body?.cancel().catch(() => undefined);
    return UNREADABLE;
  }
  if (body === null) {
    return "";
  }
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    total += value.byteLength;
    if (total > MAX_RESPONSE_BYTES) {
      void reader.cancel().catch(() => undefined);
      return UNREADABLE;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return UNREADABLE;
  }
}

function failure(code: ExtractErrorCode): ExtractResult {
  return { ok: false, code };
}

function interpret(status: number, body: unknown, file: Blob, headers: Headers): ExtractResult {
  if (!isPlainObject(body)) {
    return failure("unknown_error");
  }
  if (status === 200) {
    const kind = ownValue(body, "kind");
    const bytes = ownValue(body, "bytes");
    if (
      typeof kind === "string" &&
      FILE_KINDS.has(kind) &&
      typeof bytes === "number" &&
      Number.isSafeInteger(bytes) &&
      bytes === file.size
    ) {
      return { ok: true, kind: kind as FileKind, bytes };
    }
    return failure("unknown_error");
  }
  const code = ownValue(body, "error");
  if (typeof code !== "string" || !isServerErrorCode(status, code)) {
    return failure("unknown_error");
  }
  if (code === "busy") {
    const retryAfterSeconds = parseRetryAfter(headers.get("Retry-After"));
    return retryAfterSeconds === undefined
      ? { ok: false, code }
      : { ok: false, code, retryAfterSeconds };
  }
  return { ok: false, code };
}

/**
 * Sends one file to the server for the type check. Never throws.
 * The result never contains text from the server.
 */
export async function extractFile(
  file: Blob,
  options: ExtractOptions = {},
): Promise<ExtractResult> {
  const { signal, fetchImpl, timeoutMs = DEFAULT_EXTRACT_TIMEOUT_MS } = options;
  if (signal?.aborted === true) {
    return failure("aborted");
  }

  const controller = new AbortController();
  let timedOut = false;
  const onCallerAbort = (): void => {
    controller.abort();
  };
  signal?.addEventListener("abort", onCallerAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  /** Why the request stopped early, if it did. */
  const stopReason = (fallback: ExtractErrorCode): ExtractErrorCode => {
    if (timedOut) {
      return "timeout";
    }
    if (signal?.aborted === true) {
      return "aborted";
    }
    return fallback;
  };

  try {
    let response: Response;
    let text: string | typeof UNREADABLE;
    try {
      // Read the global at call time, so a replaced `fetch` is used.
      const doFetch = fetchImpl ?? globalThis.fetch;
      response = await doFetch(EXTRACT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
        signal: controller.signal,
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
      if (!isJson(response.headers)) {
        void response.body?.cancel().catch(() => undefined);
        return failure("unknown_error");
      }
      text = await readCapped(response);
    } catch {
      return failure(stopReason("network_error"));
    }
    if (controller.signal.aborted) {
      return failure(stopReason("aborted"));
    }
    if (text === UNREADABLE) {
      return failure("unknown_error");
    }
    return interpret(response.status, parseJson(text), file, response.headers);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}
