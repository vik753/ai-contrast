/**
 * Client for `POST /api/segment` (S5-T1 contract, ADR 0014).
 *
 * - The body is `{"blocks": [{text, part, page}]}` as a JSON string: only the
 *   text blocks of one row, never a file name (threat model T3, T11).
 * - The request goes through the shared core of `extract.ts` (fetch options,
 *   capped read, allowlisted error codes, strict `200` validation).
 * - A `200` body is validated strictly and fails closed as `invalid_response`:
 *   caps, spans inside the returned blocks, spans in order inside a clause,
 *   no character in two clauses, the heading inside its clause (T3 control 7,
 *   T6). Span offsets are code points, like the server counts them.
 * - Clause text is built from spans over the returned (cleaned) blocks; the
 *   reply holds no copy of it. Everything is plain text (threat model T1).
 */
import {
  MAX_BLOCKS,
  MAX_PAGES,
  MAX_WARNINGS,
  hasExactKeys,
  isCode,
  isPageOf,
  isPlainObject,
  parseBlocks,
  parseRemoved,
  postValidated,
  type Block,
  type ErrorTable,
  type ExtractOptions,
  type PostFailure,
  type RemovedText,
  type ServerErrorCode,
} from "./extract";

export const SEGMENT_URL = "/api/segment";

/** Client caps, equal to the server cap `SEGMENT_MAX_CLAUSES`. */
export const MAX_CLAUSES = 2_000;

/** Longest clause number we accept (a short label such as "3.2.1" or "(a)"). */
const MAX_NUMBER_CHARS = 200;
const MAX_LEVEL = 1_000;

export type ClausePart = Block["part"] | "running" | "preamble";

/** `[block index, start, end)` into the returned blocks, offsets in code points. */
export type Span = readonly [number, number, number];

export interface Clause {
  readonly id: string;
  readonly number: string | null;
  readonly level: number;
  readonly partIndex: number;
  readonly sectionKind: "requisites" | null;
  readonly part: ClausePart;
  readonly pages: readonly number[];
  readonly spans: readonly Span[];
  readonly headingSpan: Span | null;
}

export interface SegmentWarning {
  readonly code: string;
  /** The clause id the warning is about, or `null` for the whole document. */
  readonly clause: string | null;
}

/** Identifier classes of ADR 0008 point 1 (the server's `EntityClass`). */
export const ENTITY_CLASSES = [
  "ORG",
  "PERSON",
  "TAX_ID",
  "ACCOUNT",
  "ADDRESS",
  "PHONE",
  "EMAIL",
  "URL",
  "PERSONAL_DOC",
  "DOC_NO",
  "VEHICLE",
  "SIGNATURE",
  "HEALTH",
] as const;
export type EntityClass = (typeof ENTITY_CLASSES)[number];

/** One identifier of the document: every occurrence, no value string (ADR 0015 point 1). */
export interface Entity {
  readonly id: string;
  readonly cls: EntityClass;
  readonly precision: "high" | "normal";
  readonly spans: readonly Span[];
}

export interface RequisitesLine {
  readonly span: Span;
  readonly action: "drop" | "keep";
}

export interface RequisitesClause {
  readonly clause: string;
  readonly lines: readonly RequisitesLine[];
}

/** What the detector found (S5b). Spans point into the returned blocks. */
export interface Detection {
  readonly detectorVersion: string;
  readonly entities: readonly Entity[];
  readonly requisites: readonly RequisitesClause[];
  /** Placeholder look-alikes, already neutralized (`⟦…⟧`) in the returned blocks. */
  readonly neutralized: readonly Span[];
}

/** The validated reply. Kept in memory only. */
export interface Segmentation extends Detection {
  readonly clauses: readonly Clause[];
  readonly blocks: readonly Block[];
  readonly removed: readonly RemovedText[];
  readonly warnings: readonly SegmentWarning[];
}

export interface SegmentSuccess {
  ok: true;
  segmentation: Segmentation;
}
export type SegmentResult = SegmentSuccess | PostFailure;

const SEGMENT_ERRORS: ErrorTable = new Map<number, ReadonlySet<ServerErrorCode>>([
  [411, new Set(["length_required"])],
  [413, new Set(["request_too_large"])],
  [415, new Set(["unsupported_media_type"])],
  [
    422,
    new Set([
      "invalid_request",
      "too_much_text",
      "no_text_extracted",
      "too_many_clauses",
      "clause_too_long",
      "too_many_identifiers",
      "segment_failed",
    ]),
  ],
  [408, new Set(["upload_timeout"])],
  [503, new Set(["busy"])],
  [504, new Set(["segment_timeout"])],
]);

const CLAUSE_PARTS: ReadonlySet<string> = new Set<ClausePart>([
  "body",
  "footnote",
  "endnote",
  "header",
  "footer",
  "textbox",
  "running",
  "preamble",
]);

const CLAUSE_KEYS = [
  "id",
  "number",
  "level",
  "part_index",
  "section_kind",
  "part",
  "pages",
  "spans",
  "heading_span",
] as const;
const WARNING_KEYS = ["code", "clause"] as const;
const RESULT_KEYS = [
  "clauses",
  "blocks",
  "removed",
  "warnings",
  "detector_version",
  "entities",
  "requisites",
  "neutralized",
] as const;
const ENTITY_KEYS = ["id", "class", "precision", "spans"] as const;
const REQUISITES_KEYS = ["clause", "lines"] as const;
const LINE_KEYS = ["span", "action"] as const;

/** Caps equal to the server's (ADR 0015 point 1). */
export const MAX_ENTITIES = 5_000;
export const MAX_ENTITY_SPANS = 50_000;
/** Most spans of different entities that may overlap one position (ORG, PERSON, SIGNATURE…). */
const MAX_OVERLAP_DEPTH = 8;

const ENTITY_ID = /^e[1-9][0-9]{0,4}$/;
const VERSION = /^[a-z0-9-]{1,64}$/;
const CLASS_SET: ReadonlySet<string> = new Set(ENTITY_CLASSES);

const SURROGATE = /[\ud800-\udfff]/;

/**
 * Maps code point offsets (what the server counts) to UTF-16 offsets, built once
 * per block. `units` is `null` when the block has no surrogate: offsets are equal.
 */
interface BlockIndex {
  readonly text: string;
  /** Length in code points. */
  readonly length: number;
  readonly units: Uint32Array | null;
}

function buildIndex(text: string): BlockIndex {
  if (!SURROGATE.test(text)) {
    return { text, length: text.length, units: null };
  }
  const units: number[] = [];
  for (let i = 0; i < text.length; i += 1) {
    units.push(i);
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i += 1;
      }
    }
  }
  units.push(text.length);
  return { text, length: units.length - 1, units: Uint32Array.from(units) };
}

/** Indexes of blocks already built, so clause text never rescans a block. */
const INDEXES = new WeakMap<Block, BlockIndex>();

function indexOf(block: Block): BlockIndex {
  let index = INDEXES.get(block);
  if (index === undefined) {
    index = buildIndex(block.text);
    INDEXES.set(block, index);
  }
  return index;
}

/** The part of a block between two code point offsets. */
function sliceIndex(index: BlockIndex, start: number, end: number): string {
  return index.units === null
    ? index.text.slice(start, end)
    : index.text.slice(index.units[start], index.units[end]);
}

function isOffset(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/** A span with offsets inside the block, or `null`. */
function parseSpan(value: unknown, lengths: readonly number[]): Span | null {
  if (!Array.isArray(value) || value.length !== 3) {
    return null;
  }
  const [index, start, end] = value as unknown[];
  if (!isOffset(index) || !isOffset(start) || !isOffset(end)) {
    return null;
  }
  const length = lengths[index];
  return length !== undefined && start <= end && end <= length ? [index, start, end] : null;
}

/** Spans in document order and not overlapping: each starts at or after the end of the last. */
function inOrder(spans: readonly Span[]): boolean {
  let last: Span | null = null;
  for (const span of spans) {
    if (last !== null && (span[0] < last[0] || (span[0] === last[0] && span[1] < last[2]))) {
      return false;
    }
    last = span;
  }
  return true;
}

function within(inner: Span, outer: Span): boolean {
  return inner[0] === outer[0] && inner[1] >= outer[1] && inner[2] <= outer[2];
}

function parseClause(
  value: unknown,
  index: number,
  lengths: readonly number[],
  pages: number | null,
): Clause | null {
  if (!isPlainObject(value) || !hasExactKeys(value, CLAUSE_KEYS)) {
    return null;
  }
  const { id, number, level, part_index, section_kind, part, pages: clausePages } = value;
  if (
    id !== `c${String(index + 1)}` ||
    (number !== null && (typeof number !== "string" || number.length > MAX_NUMBER_CHARS)) ||
    !isOffset(level) ||
    level > MAX_LEVEL ||
    !isOffset(part_index) ||
    (section_kind !== null && section_kind !== "requisites") ||
    typeof part !== "string" ||
    !CLAUSE_PARTS.has(part) ||
    !Array.isArray(clausePages) ||
    clausePages.length > MAX_PAGES ||
    !Array.isArray(value.spans) ||
    value.spans.length === 0 ||
    value.spans.length > MAX_BLOCKS
  ) {
    return null;
  }
  let lastPage = 0;
  for (const page of clausePages as unknown[]) {
    if (!isPageOf(page, pages) || page <= lastPage) {
      return null;
    }
    lastPage = page;
  }
  const spans: Span[] = [];
  for (const item of value.spans as unknown[]) {
    const span = parseSpan(item, lengths);
    if (span === null) {
      return null;
    }
    spans.push(span);
  }
  if (!inOrder(spans)) {
    return null;
  }
  // The heading may belong to the section: it lies inside a span of some clause (checked later).
  const headingSpan = value.heading_span === null ? null : parseSpan(value.heading_span, lengths);
  if (value.heading_span !== null && headingSpan === null) {
    return null;
  }
  return {
    id,
    number,
    level,
    partIndex: part_index,
    sectionKind: section_kind,
    part: part as ClausePart,
    pages: clausePages as number[],
    spans,
    headingSpan,
  };
}

/** No character belongs to two clauses. */
function disjoint(clauses: readonly Clause[]): boolean {
  const all = clauses.flatMap((clause) => clause.spans).filter((span) => span[2] > span[1]);
  all.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  let last: Span | null = null;
  for (const span of all) {
    if (last !== null && span[0] === last[0] && span[1] < last[2]) {
      return false;
    }
    last = span;
  }
  return true;
}

/**
 * Every non-white-space character of the returned blocks is inside a clause: no
 * text can be left out of the analysis (ADR 0009, no hidden clause). Linear: each
 * gap between spans is scanned once.
 */
function covers(clauses: readonly Clause[], indexes: readonly BlockIndex[]): boolean {
  const spans = clauses.flatMap((clause) => clause.spans).filter((span) => span[2] > span[1]);
  spans.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let at = 0;
  for (const [blockIndex, index] of indexes.entries()) {
    let cursor = 0;
    for (let span = spans[at]; span?.[0] === blockIndex; span = spans[at]) {
      const [, start, end] = span;
      if (start > cursor && /\S/.test(sliceIndex(index, cursor, start))) {
        return false;
      }
      cursor = Math.max(cursor, end);
      at += 1;
    }
    if (cursor < index.length && /\S/.test(sliceIndex(index, cursor, index.length))) {
      return false;
    }
  }
  return true;
}

function parseWarnings(value: unknown, clauses: readonly Clause[]): SegmentWarning[] | null {
  if (!Array.isArray(value) || value.length > MAX_WARNINGS) {
    return null;
  }
  const ids = new Set(clauses.map((clause) => clause.id));
  const warnings: SegmentWarning[] = [];
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, WARNING_KEYS)) {
      return null;
    }
    const { code, clause } = item;
    if (!isCode(code) || (clause !== null && (typeof clause !== "string" || !ids.has(clause)))) {
      return null;
    }
    warnings.push({ code, clause });
  }
  return warnings;
}

/** Spans that the detector may put on the same text: a name that is also a company, a signature line. */
function mayOverlap(a: EntityClass, b: EntityClass): boolean {
  return (
    a === "SIGNATURE" ||
    b === "SIGNATURE" ||
    (a === "ORG" && b === "PERSON") ||
    (a === "PERSON" && b === "ORG")
  );
}

/**
 * No two spans of one entity overlap; spans of two entities overlap only for the pairs
 * of `mayOverlap`. A sweep over the spans in document order; the active set is capped,
 * so the check stays linear.
 */
function noBadOverlap(entities: readonly Entity[]): boolean {
  const all: { span: Span; owner: number }[] = [];
  for (const [owner, entity] of entities.entries()) {
    for (const span of entity.spans) {
      all.push({ span, owner });
    }
  }
  all.sort((a, b) => a.span[0] - b.span[0] || a.span[1] - b.span[1] || a.span[2] - b.span[2]);
  let active: { span: Span; owner: number }[] = [];
  for (const item of all) {
    active = active.filter(
      (other) => other.span[0] === item.span[0] && other.span[2] > item.span[1],
    );
    for (const other of active) {
      const a = entities[item.owner];
      const b = entities[other.owner];
      if (a === undefined || b === undefined) {
        return false;
      }
      if (item.owner === other.owner || !mayOverlap(a.cls, b.cls)) {
        return false;
      }
    }
    active.push(item);
    if (active.length > MAX_OVERLAP_DEPTH) {
      return false;
    }
  }
  return true;
}

function parseEntities(value: unknown, lengths: readonly number[]): Entity[] | null {
  if (!Array.isArray(value) || value.length > MAX_ENTITIES) {
    return null;
  }
  const entities: Entity[] = [];
  const ids = new Set<string>();
  let spanCount = 0;
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, ENTITY_KEYS)) {
      return null;
    }
    const { id, class: cls, precision, spans: rawSpans } = item;
    if (
      typeof id !== "string" ||
      !ENTITY_ID.test(id) ||
      ids.has(id) ||
      typeof cls !== "string" ||
      !CLASS_SET.has(cls) ||
      (precision !== "high" && precision !== "normal") ||
      !Array.isArray(rawSpans) ||
      rawSpans.length === 0
    ) {
      return null;
    }
    spanCount += rawSpans.length;
    if (spanCount > MAX_ENTITY_SPANS) {
      return null;
    }
    const spans: Span[] = [];
    for (const raw of rawSpans as unknown[]) {
      const span = parseSpan(raw, lengths);
      // An empty span would mask nothing.
      if (span === null || span[2] <= span[1]) {
        return null;
      }
      spans.push(span);
    }
    if (!inOrder(spans)) {
      return null;
    }
    ids.add(id);
    entities.push({ id, cls: cls as EntityClass, precision, spans });
  }
  return noBadOverlap(entities) ? entities : null;
}

function parseRequisites(
  value: unknown,
  lengths: readonly number[],
  clauses: readonly Clause[],
): RequisitesClause[] | null {
  if (!Array.isArray(value) || value.length > MAX_CLAUSES) {
    return null;
  }
  const ids = new Set(clauses.map((clause) => clause.id));
  const out: RequisitesClause[] = [];
  let lineCount = 0;
  for (const item of value as unknown[]) {
    if (!isPlainObject(item) || !hasExactKeys(item, REQUISITES_KEYS)) {
      return null;
    }
    const { clause, lines: rawLines } = item;
    if (typeof clause !== "string" || !ids.has(clause) || !Array.isArray(rawLines)) {
      return null;
    }
    lineCount += rawLines.length;
    if (lineCount > MAX_ENTITY_SPANS) {
      return null;
    }
    const lines: RequisitesLine[] = [];
    for (const raw of rawLines as unknown[]) {
      if (!isPlainObject(raw) || !hasExactKeys(raw, LINE_KEYS)) {
        return null;
      }
      const span = parseSpan(raw.span, lengths);
      if (span === null || (raw.action !== "drop" && raw.action !== "keep")) {
        return null;
      }
      lines.push({ span, action: raw.action });
    }
    out.push({ clause, lines });
  }
  return out;
}

function parseNeutralized(value: unknown, lengths: readonly number[]): Span[] | null {
  if (!Array.isArray(value) || value.length > MAX_ENTITY_SPANS) {
    return null;
  }
  const spans: Span[] = [];
  for (const raw of value as unknown[]) {
    const span = parseSpan(raw, lengths);
    if (span === null) {
      return null;
    }
    spans.push(span);
  }
  return spans;
}

/** The `200` body, validated strictly. `null` when anything is off. */
function parseSegmentation(
  body: Record<string, unknown>,
  pages: number | null,
): SegmentSuccess | null {
  if (!hasExactKeys(body, RESULT_KEYS)) {
    return null;
  }
  const blocks = parseBlocks(body.blocks, pages);
  const removed = parseRemoved(body.removed);
  if (
    blocks === null ||
    removed === null ||
    !Array.isArray(body.clauses) ||
    body.clauses.length === 0 ||
    body.clauses.length > MAX_CLAUSES
  ) {
    return null;
  }
  const indexes = blocks.map(indexOf);
  const lengths = indexes.map((index) => index.length);
  const clauses: Clause[] = [];
  for (const [index, item] of (body.clauses as unknown[]).entries()) {
    const clause = parseClause(item, index, lengths, pages);
    if (clause === null) {
      return null;
    }
    clauses.push(clause);
  }
  const headingsInside = clauses.every((clause) => {
    const heading = clause.headingSpan;
    return (
      heading === null || clauses.some((other) => other.spans.some((span) => within(heading, span)))
    );
  });
  const warnings = parseWarnings(body.warnings, clauses);
  if (!headingsInside || warnings === null || !disjoint(clauses) || !covers(clauses, indexes)) {
    return null;
  }
  const version = body.detector_version;
  const entities = parseEntities(body.entities, lengths);
  const requisites = parseRequisites(body.requisites, lengths, clauses);
  const neutralized = parseNeutralized(body.neutralized, lengths);
  if (
    typeof version !== "string" ||
    !VERSION.test(version) ||
    entities === null ||
    requisites === null ||
    neutralized === null
  ) {
    return null;
  }
  return {
    ok: true,
    segmentation: {
      clauses,
      blocks,
      removed,
      warnings,
      detectorVersion: version,
      entities,
      requisites,
      neutralized,
    },
  };
}

/**
 * Sends the blocks of one row for clause segmentation. `pages` is the page
 * count of the row (`null` for DOCX and text): block and clause pages are
 * checked against it. Never throws.
 */
export function segmentBlocks(
  blocks: readonly { text: string; part: string; page: number | null }[],
  pages: number | null,
  options: ExtractOptions = {},
): Promise<SegmentResult> {
  const payload = blocks.map(({ text, part, page }) => ({ text, part, page }));
  return postValidated(
    {
      url: SEGMENT_URL,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blocks: payload }),
    },
    SEGMENT_ERRORS,
    (body) => parseSegmentation(body, pages),
    options,
    "invalid_response",
  );
}

/** Offset in UTF-16 units of a code point offset of `block`. */
export function unitOffset(block: Block, codePoint: number): number {
  const index = indexOf(block);
  return index.units === null ? codePoint : (index.units[codePoint] ?? index.text.length);
}

/** Code point offset of a UTF-16 offset of `block` (the unit must start a code point). */
export function codePointOffset(block: Block, unit: number): number {
  const index = indexOf(block);
  if (index.units === null) {
    return unit;
  }
  let low = 0;
  let high = index.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((index.units[mid] ?? 0) < unit) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  return low;
}

/** Length of a block in code points. */
export function blockLength(block: Block): number {
  return indexOf(block).length;
}

/** The text of a span. */
export function spanText(blocks: readonly Block[], span: Span): string {
  const block = blocks[span[0]];
  return block === undefined ? "" : sliceIndex(indexOf(block), span[1], span[2]);
}

/** The heading text of a clause, read from its `heading_span`, or `null`. */
export function clauseHeading(blocks: readonly Block[], clause: Clause): string | null {
  return clause.headingSpan === null ? null : spanText(blocks, clause.headingSpan);
}

/**
 * The clause text without its heading: the span texts joined with a newline.
 * A span that is exactly the heading is left out (the heading is shown apart).
 */
export function clauseBody(blocks: readonly Block[], clause: Clause): string {
  const heading = clause.headingSpan;
  return clause.spans
    .filter((span) => heading?.[0] !== span[0] || heading[1] !== span[1] || heading[2] !== span[2])
    .map((span) => spanText(blocks, span))
    .join("\n");
}
