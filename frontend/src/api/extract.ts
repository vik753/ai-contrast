/**
 * Client for `POST /api/extract` (stage 2 API contract, ADR 0010).
 *
 * - The body is the file itself (raw bytes). No multipart, no file name in
 *   the URL, the headers or the body (threat model T3, T11).
 * - The only header we set is `Content-Type: application/octet-stream`.
 *   The browser adds `Content-Length` for a `Blob` body.
 * - The response must be `application/json`. A `200` body may be up to
 *   4 MiB + 64 KiB (the stage 3 extraction result); any other body at most
 *   4 KiB.
 * - The response is validated strictly: a `200` body must match the stage 3
 *   contract exactly (all fields, enums, caps, no unknown fields), like the
 *   server model (`extra="forbid"`). Error codes pass an allowlist;
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
  | "upload_timeout"
  // Stage 3 extraction (422).
  | "extraction_failed"
  | "extraction_timeout"
  | "too_many_pages"
  | "too_much_text"
  | "encrypted_unsupported"
  | "no_text_extracted"
  | "text_decoding_failed"
  | "suspicious_package"
  | "docx_strict_unsupported"
  | "pdf_damaged"
  // Temporary (501) until PDF and DOCX extraction ship.
  | "not_implemented"
  // Google Docs by public link (S3-T6): only `POST /api/extract/google-doc`.
  | "invalid_request"
  | "invalid_google_doc_id"
  | "google_doc_not_public"
  | "google_doc_not_found"
  | "google_doc_too_large"
  | "google_doc_unavailable"
  | "google_doc_timeout";

/** Error codes produced in the browser only. */
export type ClientErrorCode = "network_error" | "timeout" | "aborted" | "unknown_error";

export type ExtractErrorCode = ServerErrorCode | ClientErrorCode;

export type Language = "uk" | "ru" | "en" | "mixed" | "unknown";

export type BlockPart = "body" | "footnote" | "endnote" | "header" | "footer" | "textbox";

/** One paragraph-like block of extracted text. `page` is `null` for DOCX and text. */
export interface Block {
  readonly text: string;
  readonly part: BlockPart;
  readonly page: number | null;
}

/** Text dropped as provably invisible, per reason, with a short sample. */
export interface RemovedText {
  readonly reason: string;
  readonly count: number;
  readonly sample: string;
}

export interface ExtractionWarning {
  readonly code: string;
  readonly page: number | null;
}

/** The validated stage 3 extraction result. Kept in memory only. */
export interface Extraction {
  readonly language: Language;
  readonly pages: number | null;
  readonly blocks: readonly Block[];
  readonly ocrPages: readonly number[];
  readonly removed: readonly RemovedText[];
  readonly warnings: readonly ExtractionWarning[];
}

export type ExtractResult =
  | { ok: true; kind: FileKind; bytes: number; extraction: Extraction }
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

/** Largest error body we read. Real error answers are a few dozen bytes. */
export const MAX_RESPONSE_BYTES = 4 * 1024;

/** Largest `200` body we read: the server result cap (4 MiB) plus JSON overhead. */
export const MAX_SUCCESS_RESPONSE_BYTES = 4 * 1024 * 1024 + 64 * 1024;

/** Client caps, equal to the server caps (`EXTRACT_MAX_BLOCKS`, `EXTRACT_MAX_TEXT_CHARS`). */
export const MAX_BLOCKS = 20_000;
export const MAX_TEXT_CHARS = 1_000_000;
export const MAX_SAMPLE_CHARS = 200;

/**
 * List caps. The server must keep the same caps (S3-T2/T3 add them to the
 * server model); a body above a cap fails closed here as `unknown_error`.
 */
export const MAX_PAGES = 100;
export const MAX_REMOVED = 1_000;
export const MAX_WARNINGS = 1_000;

const FILE_KINDS: ReadonlySet<string> = new Set<FileKind>(["pdf", "docx", "text"]);

/**
 * Allowed error codes per HTTP status. A code is accepted only with the
 * status the API contract gives it. `Map` and `Set` lookups never reach
 * `Object.prototype`, so `__proto__` or `toString` cannot match.
 */
export type ErrorTable = ReadonlyMap<number, ReadonlySet<string>>;

const UPLOAD_ERRORS: ErrorTable = new Map<number, ReadonlySet<ServerErrorCode>>([
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
    ]),
  ],
  [400, new Set(["length_mismatch"])],
  [408, new Set(["upload_timeout"])],
  [501, new Set(["not_implemented"])],
  [503, new Set(["busy"])],
]);

const LANGUAGES: ReadonlySet<string> = new Set<Language>(["uk", "ru", "en", "mixed", "unknown"]);

const PARTS: ReadonlySet<string> = new Set<BlockPart>([
  "body",
  "footnote",
  "endnote",
  "header",
  "footer",
  "textbox",
]);

/** Reasons and warning codes are fixed identifiers (same pattern as the server). */
const CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

const RESULT_KEYS = [
  "kind",
  "bytes",
  "language",
  "pages",
  "blocks",
  "ocr_pages",
  "removed",
  "warnings",
] as const;
const BLOCK_KEYS = ["text", "part", "page"] as const;
const REMOVED_KEYS = ["reason", "count", "sample"] as const;
const WARNING_KEYS = ["code", "page"] as const;

function isServerErrorCode(
  errors: ErrorTable,
  status: number,
  code: string,
): code is ServerErrorCode {
  return errors.get(status)?.has(code) === true;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Exactly these own keys, no more (`extra="forbid"`). `JSON.parse` makes a
 * `"__proto__"` key an own property, so it is caught here as an unknown key.
 */
function hasExactKeys(record: Record<string, unknown>, keys: readonly string[]): boolean {
  const own = Object.keys(record);
  return own.length === keys.length && keys.every((key) => Object.hasOwn(record, key));
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isCode(value: unknown): value is string {
  return typeof value === "string" && CODE_PATTERN.test(value);
}

/**
 * Number of characters (code points, as the server counts them), counted
 * up to `limit + 1` at most. A string of at most `limit` UTF-16 units has at
 * most `limit` code points, so the caller scans only longer text.
 */
function codePointsUpTo(text: string, limit: number): number {
  let count = 0;
  for (let i = 0; i < text.length && count <= limit; i += 1) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i += 1;
      }
    }
    count += 1;
  }
  return count;
}

/** At most `limit` characters (code points) in total. */
export function withinCharCap(texts: readonly string[], limit: number): boolean {
  let units = 0;
  for (const text of texts) {
    units += text.length;
  }
  if (units <= limit) {
    return true;
  }
  let chars = 0;
  for (const text of texts) {
    chars += codePointsUpTo(text, limit - chars);
    if (chars > limit) {
      return false;
    }
  }
  return true;
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

/**
 * A page number: positive, and within `pages` for a PDF. DOCX and text have
 * no pages, so their page is always `null`.
 */
function isPageOf(value: unknown, pages: number | null): value is number {
  return pages !== null && isPositiveInt(value) && value <= pages;
}

function parseBlocks(value: unknown, pages: number | null): Block[] | null {
  if (!Array.isArray(value) || value.length > MAX_BLOCKS) {
    return null;
  }
  const blocks: Block[] = [];
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, BLOCK_KEYS)) {
      return null;
    }
    const { text, part, page } = item;
    if (typeof text !== "string" || typeof part !== "string" || !PARTS.has(part)) {
      return null;
    }
    if (pages === null ? page !== null : !isPageOf(page, pages)) {
      return null;
    }
    blocks.push({ text, part: part as BlockPart, page: page as number | null });
  }
  return withinCharCap(
    blocks.map((block) => block.text),
    MAX_TEXT_CHARS,
  )
    ? blocks
    : null;
}

function parseOcrPages(value: unknown, pages: number | null): number[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const list = value as unknown[];
  if (pages === null) {
    return list.length === 0 ? [] : null;
  }
  // Strictly increasing, so no duplicates and at most `pages` entries.
  let last = 0;
  for (const page of list) {
    if (!isPageOf(page, pages) || page <= last) {
      return null;
    }
    last = page;
  }
  return list as number[];
}

function parseRemoved(value: unknown): RemovedText[] | null {
  if (!Array.isArray(value) || value.length > MAX_REMOVED) {
    return null;
  }
  const removed: RemovedText[] = [];
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, REMOVED_KEYS)) {
      return null;
    }
    const { reason, count, sample } = item;
    if (
      !isCode(reason) ||
      !isPositiveInt(count) ||
      typeof sample !== "string" ||
      !withinCharCap([sample], MAX_SAMPLE_CHARS)
    ) {
      return null;
    }
    removed.push({ reason, count, sample });
  }
  return removed;
}

/**
 * Warnings: at most `MAX_WARNINGS`; the pages of one code are strictly
 * increasing (one warning per code and page; different codes may share a page).
 */
function parseWarnings(value: unknown, pages: number | null): ExtractionWarning[] | null {
  if (!Array.isArray(value) || value.length > MAX_WARNINGS) {
    return null;
  }
  const warnings: ExtractionWarning[] = [];
  const lastPage = new Map<string, number>();
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, WARNING_KEYS)) {
      return null;
    }
    const { code, page } = item;
    if (!isCode(code) || (page !== null && !isPageOf(page, pages))) {
      return null;
    }
    if (page !== null) {
      if (page <= (lastPage.get(code) ?? 0)) {
        return null;
      }
      lastPage.set(code, page);
    }
    warnings.push({ code, page });
  }
  return warnings;
}

/** The stage 3 `200` body, validated strictly. `null` when anything is off. */
function parseSuccess(body: Record<string, unknown>, rules: ResponseRules): ExtractResult | null {
  if (!hasExactKeys(body, RESULT_KEYS)) {
    return null;
  }
  const { kind, bytes, language, pages } = body;
  if (
    typeof kind !== "string" ||
    !FILE_KINDS.has(kind) ||
    !rules.acceptKind(kind as FileKind) ||
    typeof bytes !== "number" ||
    !Number.isSafeInteger(bytes) ||
    !rules.acceptBytes(bytes) ||
    typeof language !== "string" ||
    !LANGUAGES.has(language)
  ) {
    return null;
  }
  // Only a PDF has pages (1…MAX_PAGES); DOCX and text have `null`. Client and
  // server must agree on this nullability when S3-T3 (PDF) lands.
  if (kind === "pdf" ? !isPositiveInt(pages) || pages > MAX_PAGES : pages !== null) {
    return null;
  }
  const pageCount = pages as number | null;
  const blocks = parseBlocks(body.blocks, pageCount);
  const ocrPages = parseOcrPages(body.ocr_pages, pageCount);
  const removed = parseRemoved(body.removed);
  const warnings = parseWarnings(body.warnings, pageCount);
  if (blocks === null || ocrPages === null || removed === null || warnings === null) {
    return null;
  }
  return {
    ok: true,
    kind: kind as FileKind,
    bytes,
    extraction: {
      language: language as Language,
      pages: pageCount,
      blocks,
      ocrPages,
      removed,
      warnings,
    },
  };
}

/**
 * What a `200` body and an error body may contain for one endpoint.
 * The upload endpoint knows the file, so `bytes` must equal its size; the
 * Google Docs endpoint has no local file, so it bounds `bytes` instead.
 */
export interface ResponseRules {
  readonly errors: ErrorTable;
  readonly acceptBytes: (bytes: number) => boolean;
  readonly acceptKind: (kind: FileKind) => boolean;
}

/** What to send: the request goes to `url` with exactly these headers and body. */
export interface ExtractRequest {
  readonly url: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: BodyInit;
}

/** Marker for a body that is too large or not valid UTF-8. */
const UNREADABLE = Symbol("unreadable");

/**
 * Reads the body as UTF-8 text, at most `maxBytes`. A larger
 * declared `Content-Length` is rejected before reading; a larger streamed
 * body stops the reading and cancels the stream. Stream errors are thrown.
 */
async function readCapped(
  response: Response,
  maxBytes: number,
  signal: AbortSignal,
): Promise<string | typeof UNREADABLE> {
  const body = response.body;
  const declared = response.headers.get("Content-Length");
  if (declared !== null && (!/^\d+$/.test(declared.trim()) || Number(declared) > maxBytes)) {
    void body?.cancel().catch(() => undefined);
    return UNREADABLE;
  }
  if (body === null) {
    return "";
  }
  const reader = body.getReader();
  // A stalled body must not outlive the timeout or an abort: cancelling the
  // reader ends a pending read. The caller then sees the abort and discards the text.
  const onAbort = (): void => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", onAbort, { once: true });
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      total += value.byteLength;
      if (total > maxBytes) {
        void reader.cancel().catch(() => undefined);
        return UNREADABLE;
      }
      chunks.push(value);
    }
  } finally {
    signal.removeEventListener("abort", onAbort);
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

function interpret(
  status: number,
  body: unknown,
  rules: ResponseRules,
  headers: Headers,
): ExtractResult {
  if (!isPlainObject(body)) {
    return failure("unknown_error");
  }
  if (status === 200) {
    return parseSuccess(body, rules) ?? failure("unknown_error");
  }
  const code = ownValue(body, "error");
  if (typeof code !== "string" || !isServerErrorCode(rules.errors, status, code)) {
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
 * Sends one request to an extraction endpoint and validates the answer with
 * `rules`. Shared by `extractFile` and `extractGoogleDoc`. Never throws. An
 * error result never contains text from the server; an ok result carries the
 * validated extraction (plain text, shown as text only).
 */
export async function postExtract(
  request: ExtractRequest,
  rules: ResponseRules,
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
      response = await doFetch(request.url, {
        method: "POST",
        headers: { ...request.headers },
        body: request.body,
        signal: controller.signal,
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
      if (!isJson(response.headers)) {
        void response.body?.cancel().catch(() => undefined);
        return failure("unknown_error");
      }
      text = await readCapped(
        response,
        response.status === 200 ? MAX_SUCCESS_RESPONSE_BYTES : MAX_RESPONSE_BYTES,
        controller.signal,
      );
    } catch {
      return failure(stopReason("network_error"));
    }
    if (controller.signal.aborted) {
      return failure(stopReason("aborted"));
    }
    if (text === UNREADABLE) {
      return failure("unknown_error");
    }
    return interpret(response.status, parseJson(text), rules, response.headers);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}

/**
 * Sends one file to the server for the type check and text extraction.
 * Never throws (see `postExtract`).
 */
export function extractFile(file: Blob, options: ExtractOptions = {}): Promise<ExtractResult> {
  return postExtract(
    {
      url: EXTRACT_URL,
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    },
    {
      errors: UPLOAD_ERRORS,
      acceptBytes: (bytes) => bytes === file.size,
      acceptKind: () => true,
    },
    options,
  );
}
