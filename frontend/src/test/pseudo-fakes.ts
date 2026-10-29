/**
 * Test helpers for S5b-T3 (preview and masking). Synthetic data only.
 *
 * ASSUMED NAMES (the implementation must match; the tech lead may rename):
 * - `api/segment.ts`: `segmentBlocks` returns, besides the old fields,
 *   `detectorVersion`, `entities[{id, cls, precision, spans}]`,
 *   `requisites[{clause, lines[{span, action}]}]`, `neutralized` (spans);
 *   new error code `too_many_identifiers` (422).
 * - `api/safetyCheck.ts`: `checkSafety(doc, options)`.
 * - `pseudo/masking.ts`: pure review functions (see masking.test.ts).
 */
import { vi } from "vitest";
import type { Segmentation } from "../api/segment";
import { segmentBlocks } from "../api/segment";
import { jsonResponse } from "./upload-fakes";
import type { WireBlock } from "./segment-fakes";
import { body, segmentReply } from "./segment-fakes";

export interface WireEntity {
  id: string;
  class: string;
  precision: string;
  spans: [number, number, number][];
}

/** Every occurrence of `needle` in block `index`, as wire spans (code points = UTF-16 here). */
export function occurrences(
  blocks: readonly WireBlock[],
  index: number,
  needle: string,
): [number, number, number][] {
  const text = blocks[index]?.text ?? "";
  const out: [number, number, number][] = [];
  for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + 1)) {
    out.push([index, at, at + needle.length]);
  }
  if (out.length === 0) {
    throw new Error(`fixture: ${needle} not in block ${String(index)}`);
  }
  return out;
}

/** The JSON string body of a request (all JSON requests of the client are strings). */
function bodyText(init?: RequestInit): string {
  const body = init?.body;
  if (typeof body !== "string") {
    throw new Error("expected a JSON string body");
  }
  return body;
}

/**
 * Offsets of the `n`-th `needle` in MASKED clause text. `acknowledged_unmasked` and the
 * `unmasked_identifier` spans use these offsets (the server sees only masked text).
 */
export function maskedSpan(maskedText: string, needle: string, n = 0): [number, number] {
  let at = -1;
  for (let i = 0; i <= n; i += 1) {
    at = maskedText.indexOf(needle, at + 1);
    if (at < 0) throw new Error(`fixture: ${needle} not in masked text`);
  }
  return [at, at + needle.length];
}

export const DETECTOR_VERSION = "det-2026-10-28";

export const BLOCKS: WireBlock[] = [
  body("Seller ACME LLC and John Smith agree. John Smith pays ACME LLC within 30 days."),
  body("Contact: seller@acme.example, tax code 1234567890."),
  body("Ref code 9876543210 applies to Beta Inc."),
];

const at = (b: number, needle: string) => occurrences(BLOCKS, b, needle);

/**
 * Listed in an order that differs from the document order on purpose:
 * Beta Inc (ORG, last in the text) is listed before ACME LLC (ORG, first in the text).
 */
export const ENTITIES: WireEntity[] = [
  { id: "e1", class: "PERSON", precision: "normal", spans: at(0, "John Smith") },
  { id: "e2", class: "ORG", precision: "normal", spans: at(2, "Beta Inc") },
  { id: "e3", class: "ORG", precision: "normal", spans: at(0, "ACME LLC") },
  { id: "e4", class: "EMAIL", precision: "high", spans: at(1, "seller@acme.example") },
  { id: "e5", class: "TAX_ID", precision: "high", spans: at(1, "1234567890") },
  { id: "e6", class: "TAX_ID", precision: "normal", spans: at(2, "9876543210") },
];

export const EXPECTED_MASKED = [
  "Seller [A.ORG_1] and [A.PERSON_1] agree. [A.PERSON_1] pays [A.ORG_1] within 30 days.",
  "Contact: [A.EMAIL_1], tax code [A.TAX_ID_1].",
  "Ref code [A.TAX_ID_2] applies to [A.ORG_2].",
];

/** Original values that must never leave the browser (except in `/api/segment` requests). */
export const SECRETS = [
  "ACME LLC",
  "John Smith",
  "Beta Inc",
  "seller@acme.example",
  "1234567890",
  "9876543210",
  "ACME",
  "Smith",
];

export function fixtureReply(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...segmentReply(BLOCKS),
    detector_version: DETECTOR_VERSION,
    entities: ENTITIES,
    requisites: [],
    neutralized: [],
    ...overrides,
  };
}

/** A strictly validated `Segmentation` for the fixture, through the real client. */
export async function parsedFixture(
  overrides: Record<string, unknown> = {},
  blocks: readonly WireBlock[] = BLOCKS,
  reply?: Record<string, unknown>,
): Promise<Segmentation> {
  const result = await segmentBlocks(blocks, null, {
    fetchImpl: () => Promise.resolve(jsonResponse(200, reply ?? fixtureReply(overrides))),
  });
  if (!result.ok) {
    throw new Error(`fixture rejected: ${result.code}`);
  }
  return result.segmentation;
}

export interface RecordedRequest {
  url: string;
  body: unknown;
}

/**
 * Installs a `fetch` that answers `/api/segment` with `segmentReplyFor(blocks)`,
 * `/api/safety-check` with `safety(body)`, `/api/extract` with `extract`, and records
 * every request. Any other URL throws.
 */
export function installRouter(handlers: {
  extract: (body: unknown) => Response;
  segment: (blocks: WireBlock[]) => Response;
  safety: (body: Record<string, unknown>) => Response;
}): RecordedRequest[] {
  const recorded: RecordedRequest[] = [];
  vi.stubGlobal("fetch", (input: unknown, init?: RequestInit) => {
    const url = String(input);
    recorded.push({ url, body: init?.body });
    if (url.includes("/api/safety-check")) {
      return Promise.resolve(
        handlers.safety(JSON.parse(bodyText(init)) as Record<string, unknown>),
      );
    }
    if (url.includes("/api/segment")) {
      const parsed = JSON.parse(bodyText(init)) as { blocks: WireBlock[] };
      return Promise.resolve(handlers.segment(parsed.blocks));
    }
    if (url.includes("/api/extract")) {
      return Promise.resolve(handlers.extract(init?.body));
    }
    return Promise.reject(new Error(`unexpected request to ${url}`));
  });
  return recorded;
}

/** Narrows `undefined`/`null` away, or fails the test with a clear message. */
export function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) {
    throw new Error("fixture: expected a value");
  }
  return value;
}
