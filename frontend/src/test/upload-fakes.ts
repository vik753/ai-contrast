/**
 * Test helpers for S2-T2 (upload form): fake files, a controllable fake
 * `fetch` and locale lookups that do not depend on exact key names.
 *
 * Everything here is synthetic. No real network call is ever made.
 */
import { vi } from "vitest";
import type { ExtractResult, Extraction } from "../api/extract";
import type { FlatLocale } from "./locale-utils";

export const MIB = 1024 * 1024;

/** A small `File`. `size` may be faked so that tests never allocate megabytes. */
export function makeFile(
  name: string,
  options: { content?: string; size?: number; type?: string } = {},
): File {
  const file = new File([options.content ?? "%PDF-1.7 synthetic"], name, {
    type: options.type ?? "",
  });
  if (options.size !== undefined) {
    Object.defineProperty(file, "size", { configurable: true, value: options.size });
  }
  return file;
}

/** A `FileList`-like object (jsdom cannot build a real one). */
export function fileList(files: File[]): FileList {
  const list: Record<string | number | symbol, unknown> = {
    length: files.length,
    item: (index: number) => files[index] ?? null,
    [Symbol.iterator]: function* () {
      yield* files;
    },
  };
  files.forEach((file, index) => {
    list[index] = file;
  });
  return list as unknown as FileList;
}

export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

type Kind = "pdf" | "docx" | "text";

/**
 * Stage 3 `200` body (wire format, snake_case), valid by default:
 * one body block, no OCR pages, nothing removed, no warnings.
 * PDF gets `pages: 1` and `page: 1`; DOCX and text get `null`.
 */
export function stage3Body(
  kind: Kind,
  bytes: number,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const page = kind === "pdf" ? 1 : null;
  return {
    kind,
    bytes,
    language: "en",
    pages: page,
    blocks: [{ text: "Synthetic clause one.", part: "body", page }],
    ocr_pages: [],
    removed: [],
    warnings: [],
    ...overrides,
  };
}

/** The `Extraction` the client must build from `stage3Body` (camelCase). */
export function toExtraction(body: Record<string, unknown>): Extraction {
  return {
    language: body.language,
    pages: body.pages,
    blocks: body.blocks,
    ocrPages: body.ocr_pages,
    removed: body.removed,
    warnings: body.warnings,
  } as Extraction;
}

/** A valid stage 3 `200` response. */
export function okResponse(
  kind: Kind,
  bytes: number,
  overrides: Record<string, unknown> = {},
): Response {
  return jsonResponse(200, stage3Body(kind, bytes, overrides));
}

/** The `ExtractResult` that `okResponse(kind, bytes, overrides)` must give. */
export function okResult(
  kind: Kind,
  bytes: number,
  overrides: Record<string, unknown> = {},
): ExtractResult {
  return { ok: true, kind, bytes, extraction: toExtraction(stage3Body(kind, bytes, overrides)) };
}

export function busyResponse(retryAfter: string | null = "5"): Response {
  return jsonResponse(
    503,
    { error: "busy" },
    retryAfter === null ? {} : { "Retry-After": retryAfter },
  );
}

export interface FakeCall {
  readonly input: unknown;
  readonly init: RequestInit | undefined;
  readonly body: unknown;
  readonly signal: AbortSignal | undefined;
  respond(response: Response): void;
  fail(error: unknown): void;
  readonly settled: boolean;
}

/**
 * A fake `fetch`. Every call stays pending until the test answers it with
 * `respond()` / `fail()`, unless `autoRespond` is set. A call rejects with an
 * `AbortError` when its signal aborts, like the real `fetch`.
 */
export class FakeFetch {
  readonly calls: FakeCall[] = [];
  autoRespond: ((body: unknown) => Response) | null = null;

  readonly fetch = vi.fn((input: unknown, init?: RequestInit): Promise<Response> => {
    return new Promise<Response>((resolve, reject) => {
      let settled = false;
      const signal = init?.signal ?? undefined;
      const call: FakeCall = {
        input,
        init,
        body: init?.body,
        signal,
        respond: (response) => {
          if (!settled) {
            settled = true;
            resolve(response);
          }
        },
        fail: (error) => {
          if (!settled) {
            settled = true;
            reject(error instanceof Error ? error : new Error(String(error)));
          }
        },
        get settled() {
          return settled;
        },
      };
      this.calls.push(call);
      if (signal?.aborted === true) {
        call.fail(new DOMException("The operation was aborted.", "AbortError"));
        return;
      }
      signal?.addEventListener("abort", () => {
        call.fail(new DOMException("The operation was aborted.", "AbortError"));
      });
      if (this.autoRespond !== null) {
        call.respond(this.autoRespond(init?.body));
      }
    });
  });

  /** Calls whose promise is still pending. */
  pending(): FakeCall[] {
    return this.calls.filter((c) => !c.settled);
  }

  /** The call whose body is exactly `file`. */
  callFor(file: Blob): FakeCall {
    const call = this.calls.find((c) => c.body === file);
    if (call === undefined) {
      throw new Error("No request was sent for this file");
    }
    return call;
  }

  asFetch(): typeof fetch {
    return this.fetch;
  }
}

/** Default server answer: accept the body as a PDF with the right size. */
export function acceptAsPdf(body: unknown): Response {
  const size = body instanceof Blob ? body.size : -1;
  return okResponse("pdf", size);
}

/** Replaces `{{name}}` placeholders, as i18next does. */
export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, name: string) =>
    name in values ? String(values[name]) : match,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A regular expression for a whole locale value; placeholders match any text. */
export function templateRegExp(template: string): RegExp {
  const parts = template.trim().split(/\{\{\s*\w+\s*\}\}/);
  return new RegExp(`^${parts.map(escapeRegExp).join(".+?")}$`, "s");
}

/**
 * The unique key of `locale` whose value contains `phrase`, restricted to
 * keys that start with `prefix` when given. Lets tests use the English copy
 * from the acceptance criteria without fixing the key names.
 */
export function keyContaining(locale: FlatLocale, phrase: string, prefix = ""): string {
  const keys = Object.entries(locale)
    .filter(
      ([key, value]) =>
        key.startsWith(prefix) && typeof value === "string" && value.includes(phrase),
    )
    .map(([key]) => key);
  if (keys.length === 0) {
    throw new Error(`No locale value contains ${JSON.stringify(phrase)}`);
  }
  // Plural forms of one key count as one key: prefer the `_other` form.
  const bases = new Set(keys.map(pluralBase));
  if (bases.size > 1) {
    throw new Error(
      `More than one locale key contains ${JSON.stringify(phrase)}: ${keys.join(", ")}`,
    );
  }
  return keys.find((k) => k.endsWith("_other")) ?? keys[0] ?? "";
}

export const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

export function pluralBase(key: string): string {
  return key.replace(PLURAL_SUFFIX, "");
}

/** A synthetic canary that never occurs in real data. */
export function canary(prefix: string): string {
  return `${prefix}-CANARY-${Math.random().toString(36).slice(2, 10)}`;
}
