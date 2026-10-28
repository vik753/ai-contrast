/**
 * Client for `POST /api/safety-check` (ADR 0015 point 4).
 *
 * - The body is the masked document: `label`, `detector_version`, the masked
 *   clauses and the spans the client chose to leave unmasked. No file name, no
 *   mapping, no original value of a masked entity (threat model T11).
 * - It goes through the shared core of `extract.ts` (fetch options, capped read,
 *   allowlisted error codes). A `200` body is validated strictly; the digest is
 *   informational only.
 * - `unmasked_identifier` carries offsets only: `[clause id, start, end]`.
 */
import {
  hasExactKeys,
  postValidated,
  type ErrorExtras,
  type ErrorTable,
  type ExtractOptions,
  type PostFailure,
  type ServerErrorCode,
} from "./extract";

export const SAFETY_URL = "/api/safety-check";

/** Same cap as the server for `acknowledged_unmasked` and for the spans it reports. */
export const MAX_SAFETY_SPANS = 50_000;

/** `[clause id, start, end)` in code points, relative to the clause text. */
export type ClauseSpan = readonly [string, number, number];

export interface MaskedClause {
  readonly id: string;
  readonly text: string;
}

export interface SafetyDocument {
  readonly label: string;
  readonly detectorVersion: string;
  readonly clauses: readonly MaskedClause[];
  readonly acknowledgedUnmasked: readonly ClauseSpan[];
}

export interface SafetySuccess {
  ok: true;
  detectorVersion: string;
  digest: string;
}
export type SafetyResult = SafetySuccess | PostFailure;

const SAFETY_ERRORS: ErrorTable = new Map<number, ReadonlySet<ServerErrorCode>>([
  [411, new Set(["length_required"])],
  [413, new Set(["request_too_large"])],
  [415, new Set(["unsupported_media_type"])],
  [
    422,
    new Set([
      "input_not_clean",
      "invalid_placeholder",
      "unmasked_identifier",
      "invalid_request",
      "safety_failed",
    ]),
  ],
  [408, new Set(["upload_timeout"])],
  [409, new Set(["detector_version_mismatch"])],
  [503, new Set(["busy"])],
  [504, new Set(["safety_timeout"])],
]);

const RESULT_KEYS = ["ok", "detector_version", "digest"] as const;
const VERSION_PATTERN = /^[a-z0-9-]{1,64}$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const CLAUSE_ID_PATTERN = /^c[1-9][0-9]{0,6}$/;

function parseSuccess(body: Record<string, unknown>): SafetySuccess | null {
  const { ok, detector_version: version, digest } = body;
  if (
    !hasExactKeys(body, RESULT_KEYS) ||
    ok !== true ||
    typeof version !== "string" ||
    !VERSION_PATTERN.test(version) ||
    typeof digest !== "string" ||
    !DIGEST_PATTERN.test(digest)
  ) {
    return null;
  }
  return { ok: true, detectorVersion: version, digest };
}

function parseSpans(value: unknown): ClauseSpan[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_SAFETY_SPANS) {
    return null;
  }
  const spans: ClauseSpan[] = [];
  for (const item of value as unknown[]) {
    if (!Array.isArray(item) || item.length !== 3) {
      return null;
    }
    const [id, start, end] = item as unknown[];
    if (
      typeof id !== "string" ||
      !CLAUSE_ID_PATTERN.test(id) ||
      typeof start !== "number" ||
      typeof end !== "number" ||
      !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) ||
      start < 0 ||
      end <= start
    ) {
      return null;
    }
    spans.push([id, start, end]);
  }
  return spans;
}

/** The only error body with more than `error`: `unmasked_identifier` with its spans. */
const errorExtras: ErrorExtras = (code, body) => {
  if (code !== "unmasked_identifier") {
    return {};
  }
  if (!hasExactKeys(body, ["error", "spans"])) {
    return null;
  }
  const spans = parseSpans(body.spans);
  return spans === null ? null : { spans };
};

/** Sends one masked document for the safety check. Never throws. */
export function checkSafety(
  document: SafetyDocument,
  options: ExtractOptions = {},
): Promise<SafetyResult> {
  return postValidated(
    {
      url: SAFETY_URL,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: document.label,
        detector_version: document.detectorVersion,
        clauses: document.clauses.map(({ id, text }) => ({ id, text })),
        acknowledged_unmasked: document.acknowledgedUnmasked.map((span) => [...span]),
      }),
    },
    SAFETY_ERRORS,
    parseSuccess,
    options,
    "invalid_response",
    errorExtras,
  );
}
