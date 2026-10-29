/**
 * Replacement review of one contract (S5b-T3, ADR 0015 point 3). Pure functions, no DOM.
 *
 * - A `Review` is an immutable value: the detected entities (from `/api/segment`), the
 *   client's choices (unmask, manual masks) and the cleaned blocks. Every edit returns
 *   a new value.
 * - Placeholders `[A.ORG_1]` are assigned here, in the browser, in first-occurrence
 *   order per document and class. The masked clauses and the mapping
 *   (placeholder -> original) are derived from the review and live in memory only
 *   (ADR 0013 point 9a): nothing here stores, logs or sends them. The mapping is never
 *   part of any request; the masked clauses are the only text that goes to the safety
 *   check.
 * - Clause text = the spans of the clause joined with "\n" (heading included). A requisites
 *   line that the server marked `drop` is left out unless the client unmasked a value in it.
 * - Offsets are code points (the server counts them so). Clause-relative offsets count the
 *   MASKED clause text (the only text the server sees): `acknowledgedUnmasked` returns them,
 *   and `applyUnmaskedIdentifiers` takes them from the server and maps them back.
 */
import { spanText, unitOffset, codePointOffset, blockLength } from "../api/segment";
import type { ClauseSpan, MaskedClause } from "../api/safetyCheck";
import {
  ENTITY_CLASSES,
  type Clause,
  type EntityClass,
  type RequisitesClause,
  type Segmentation,
  type Span,
} from "../api/segment";

export type { ClauseSpan, MaskedClause };

/** Classes of checksummed codes: never unmasked, even when found without context. */
const CODE_CLASSES: ReadonlySet<EntityClass> = new Set<EntityClass>(["TAX_ID", "ACCOUNT"]);

const CLASS_SET: ReadonlySet<string> = new Set(ENTITY_CLASSES);

/** Class of a span that the server found unmasked and the browser has no entity for. */
export const PREMASK_CLASS: EntityClass = "DOC_NO";

export interface Occurrence {
  readonly span: Span;
  readonly masked: boolean;
  /** Masked again after a safety-check answer: the client must confirm it. */
  readonly premasked?: true;
}

export interface ReviewEntity {
  readonly id: string;
  readonly cls: EntityClass;
  readonly precision: "high" | "normal";
  /** Added by the client (selection or server answer): no detector hit behind it. */
  readonly manual: boolean;
  /** In document order. */
  readonly occurrences: readonly Occurrence[];
}

export interface Review {
  readonly label: string;
  readonly detectorVersion: string;
  /** The cleaned blocks, clauses and warnings of the contract. */
  readonly segmentation: Segmentation;
  readonly entities: readonly ReviewEntity[];
  readonly manualCount: number;
}

/* ------------------------------------------------------------------------------------------ */
/* Several files in one contract                                                               */
/* ------------------------------------------------------------------------------------------ */

/**
 * One document from the rows of a contract: blocks follow each other, clause and entity
 * ids are numbered again. One row: the value itself.
 */
export function mergeSegmentations(parts: readonly Segmentation[]): Segmentation | null {
  const first = parts[0];
  if (first === undefined) {
    return null;
  }
  if (parts.length === 1) {
    return first;
  }
  const blocks: Segmentation["blocks"][number][] = [];
  const clauses: Clause[] = [];
  const warnings: Segmentation["warnings"][number][] = [];
  const entities: Segmentation["entities"][number][] = [];
  const requisites: RequisitesClause[] = [];
  const neutralized: Span[] = [];
  const removed: Segmentation["removed"][number][] = [];
  for (const part of parts) {
    const shift = blocks.length;
    const base = clauses.length;
    const move = (span: Span): Span => [span[0] + shift, span[1], span[2]];
    const rename = new Map(part.clauses.map((c, i) => [c.id, `c${String(base + i + 1)}`]));
    blocks.push(...part.blocks);
    removed.push(...part.removed);
    for (const clause of part.clauses) {
      clauses.push({
        ...clause,
        id: rename.get(clause.id) ?? clause.id,
        spans: clause.spans.map(move),
        headingSpan: clause.headingSpan === null ? null : move(clause.headingSpan),
      });
    }
    for (const w of part.warnings) {
      warnings.push({
        code: w.code,
        clause: w.clause === null ? null : (rename.get(w.clause) ?? null),
      });
    }
    for (const entity of part.entities) {
      entities.push({
        ...entity,
        id: `e${String(entities.length + 1)}`,
        spans: entity.spans.map(move),
      });
    }
    for (const r of part.requisites) {
      requisites.push({
        clause: rename.get(r.clause) ?? r.clause,
        lines: r.lines.map((line) => ({ span: move(line.span), action: line.action })),
      });
    }
    neutralized.push(...part.neutralized.map(move));
  }
  return {
    clauses,
    blocks,
    removed,
    warnings,
    detectorVersion: first.detectorVersion,
    entities,
    requisites,
    neutralized,
  };
}

/* ------------------------------------------------------------------------------------------ */
/* The view: pieces of every clause, placeholders, masked text                                  */
/* ------------------------------------------------------------------------------------------ */

interface Annot {
  readonly start: number;
  readonly end: number;
  readonly kind: "mask" | "plain" | "neutral";
  readonly entity: number;
  readonly index: number;
}

export type Piece =
  | {
      readonly kind: "text";
      readonly text: string;
      /** `-1` for the line break between spans. */
      readonly block: number;
      readonly start: number;
      /** An unmasked occurrence of an entity. */
      readonly occ?: { readonly entity: number; readonly index: number };
    }
  | {
      readonly kind: "mark";
      readonly text: string;
      readonly block: number;
      readonly start: number;
      readonly entity: number;
      readonly index: number;
      readonly premasked: boolean;
    }
  | {
      readonly kind: "neutralized";
      readonly text: string;
      readonly block: number;
      readonly start: number;
    }
  | {
      readonly kind: "line";
      /** What the review does: a `drop` line with an unmasked value is kept. */
      readonly action: "drop" | "keep";
      readonly children: readonly Piece[];
    };

export interface ViewClause {
  readonly clause: Clause;
  /** One list per span of the clause. */
  readonly spans: readonly (readonly Piece[])[];
}

interface Segment {
  /** Offsets in the masked clause text (what the server sees), in code points. */
  readonly maskedStart: number;
  readonly maskedEnd: number;
  readonly block: number;
  readonly start: number;
  readonly masked: boolean;
}

export interface View {
  readonly clauses: readonly ViewClause[];
  /** Placeholder per entity index; `null` when nothing of it is in the masked text. */
  readonly placeholders: readonly (string | null)[];
  readonly mapping: ReadonlyMap<string, string>;
  readonly masked: readonly MaskedClause[];
  readonly acknowledged: readonly ClauseSpan[];
  /** Per clause id, the original-text segments (for server spans). */
  readonly segments: ReadonlyMap<string, readonly Segment[]>;
}

const VIEWS = new WeakMap<Review, View>();

function cpLength(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i += 1) {
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

/** Non-overlapping annotations per block, in document order. */
function annotations(review: Review): Map<number, Annot[]> {
  const masked: Annot[][] = [];
  const others: Annot[][] = [];
  const byBlock = (target: Annot[][], block: number): Annot[] => (target[block] ??= []);
  for (const [entity, item] of review.entities.entries()) {
    for (const [index, occurrence] of item.occurrences.entries()) {
      const [block, start, end] = occurrence.span;
      byBlock(occurrence.masked ? masked : others, block).push({
        start,
        end,
        kind: occurrence.masked ? "mask" : "plain",
        entity,
        index,
      });
    }
  }
  for (const span of review.segmentation.neutralized) {
    byBlock(others, span[0]).push({
      start: span[1],
      end: span[2],
      kind: "neutral",
      entity: -1,
      index: -1,
    });
  }
  const order = (a: Annot, b: Annot): number => a.start - b.start || b.end - a.end;
  const result = new Map<number, Annot[]>();
  const blockCount = Math.max(masked.length, others.length);
  for (let block = 0; block < blockCount; block += 1) {
    const chosen: Annot[] = [];
    let last = 0;
    for (const annot of [...(masked[block] ?? [])].sort(order)) {
      if (annot.start >= last) {
        chosen.push(annot);
        last = annot.end;
      }
    }
    // Plain occurrences and look-alikes only where no mask is.
    const free: Annot[] = [];
    let at = 0;
    for (const annot of [...(others[block] ?? [])].sort(order)) {
      while (at < chosen.length && (chosen[at]?.end ?? 0) <= annot.start) {
        at += 1;
      }
      const next = chosen[at];
      const clash = next !== undefined && next.start < annot.end;
      const lastFree = free.at(-1);
      if (!clash && (lastFree === undefined || annot.start >= lastFree.end)) {
        free.push(annot);
      }
    }
    const all = [...chosen, ...free].sort(order);
    if (all.length > 0) {
      result.set(block, all);
    }
  }
  return result;
}

/** The annotations of `list` that lie inside `[from, to)`. */
function within(list: readonly Annot[] | undefined, from: number, to: number): Annot[] {
  if (list === undefined) {
    return [];
  }
  let low = 0;
  let high = list.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((list[mid]?.start ?? 0) < from) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  const out: Annot[] = [];
  for (let i = low; i < list.length; i += 1) {
    const annot = list[i];
    if (annot === undefined || annot.start >= to) {
      break;
    }
    if (annot.end <= to) {
      out.push(annot);
    }
  }
  return out;
}

/**
 * Sorted by (clause order, start) and without overlap, like the server's check: a span
 * inside another (a person in a signature line) is left out; the server counts a normal hit
 * inside an acknowledged span as acknowledged.
 */
function outermost(spans: readonly ClauseSpan[]): ClauseSpan[] {
  const out: ClauseSpan[] = [];
  for (const span of spans) {
    const last = out.at(-1);
    if (last?.[0] === span[0] && span[1] < last[2]) {
      continue;
    }
    out.push(span);
  }
  return out;
}

function buildView(review: Review): View {
  const { segmentation } = review;
  const { blocks, clauses } = segmentation;
  const annots = annotations(review);
  const linesOf = new Map<string, RequisitesClause["lines"]>();
  for (const entry of segmentation.requisites) {
    linesOf.set(entry.clause, [...(linesOf.get(entry.clause) ?? []), ...entry.lines]);
  }
  const text = (block: number, start: number, end: number): Piece[] =>
    end > start
      ? [{ kind: "text", text: spanText(blocks, [block, start, end]), block, start }]
      : [];

  const inner = (block: number, from: number, to: number): Piece[] => {
    const pieces: Piece[] = [];
    let cursor = from;
    for (const annot of within(annots.get(block), from, to)) {
      if (annot.start < cursor) {
        continue;
      }
      pieces.push(...text(block, cursor, annot.start));
      const original = spanText(blocks, [block, annot.start, annot.end]);
      if (annot.kind === "mask") {
        const occurrence = review.entities[annot.entity]?.occurrences[annot.index];
        pieces.push({
          kind: "mark",
          text: original,
          block,
          start: annot.start,
          entity: annot.entity,
          index: annot.index,
          premasked: occurrence?.premasked === true,
        });
      } else if (annot.kind === "neutral") {
        pieces.push({ kind: "neutralized", text: original, block, start: annot.start });
      } else {
        pieces.push({
          kind: "text",
          text: original,
          block,
          start: annot.start,
          occ: { entity: annot.entity, index: annot.index },
        });
      }
      cursor = annot.end;
    }
    pieces.push(...text(block, cursor, to));
    return pieces;
  };

  const viewClauses: ViewClause[] = clauses.map((clause) => {
    const lines = linesOf.get(clause.id) ?? [];
    const spans = clause.spans.map(([block, from, to]) => {
      const mine = lines
        .filter(
          ({ span }) => span[0] === block && span[1] >= from && span[2] <= to && span[2] > span[1],
        )
        .map(({ span, action }) => ({ start: span[1], end: span[2], action }))
        .sort((a, b) => a.start - b.start);
      const pieces: Piece[] = [];
      let cursor = from;
      for (const line of mine) {
        if (line.start < cursor) {
          continue;
        }
        pieces.push(...inner(block, cursor, line.start));
        const unmaskedInside = within(annots.get(block), line.start, line.end).some(
          (a) => a.kind === "plain" && review.entities[a.entity]?.manual === false,
        );
        pieces.push({
          kind: "line",
          action: line.action === "drop" && !unmaskedInside ? "drop" : "keep",
          children: inner(block, line.start, line.end),
        });
        cursor = line.end;
      }
      pieces.push(...inner(block, cursor, to));
      return pieces;
    });
    return { clause, spans };
  });

  // Walk in document order: numbering, emitted text, original coordinates.
  const placeholders: (string | null)[] = review.entities.map(() => null);
  const counters = new Map<EntityClass, number>();
  const mapping = new Map<string, string>();
  const masked: MaskedClause[] = [];
  const acknowledged: ClauseSpan[] = [];
  const segments = new Map<string, Segment[]>();

  const assign = (entity: number, original: string): string => {
    const known = placeholders[entity];
    if (known !== undefined && known !== null) {
      return known;
    }
    const cls = review.entities[entity]?.cls ?? PREMASK_CLASS;
    const n = (counters.get(cls) ?? 0) + 1;
    counters.set(cls, n);
    const placeholder = `[${review.label}.${cls}_${String(n)}]`;
    placeholders[entity] = placeholder;
    mapping.set(placeholder, original);
    return placeholder;
  };

  for (const { clause, spans } of viewClauses) {
    const parts: string[] = [];
    const clauseSegments: Segment[] = [];
    let mpos = 0;
    const emit = (pieces: readonly Piece[], out: { text: string }): void => {
      for (const piece of pieces) {
        if (piece.kind === "line") {
          if (piece.action === "keep") {
            emit(piece.children, out);
          }
          continue;
        }
        const length = cpLength(piece.text);
        // What this piece adds to the masked text: the placeholder, or the text itself.
        const shown = piece.kind === "mark" ? assign(piece.entity, piece.text) : piece.text;
        const width = piece.kind === "mark" ? cpLength(shown) : length;
        clauseSegments.push({
          maskedStart: mpos,
          maskedEnd: mpos + width,
          block: piece.block,
          start: piece.start,
          masked: piece.kind === "mark",
        });
        out.text += shown;
        if (piece.kind !== "mark") {
          if (piece.kind === "text" && piece.occ !== undefined) {
            const owner = review.entities[piece.occ.entity];
            if (owner !== undefined && !owner.manual) {
              acknowledged.push([clause.id, mpos, mpos + length]);
            }
          }
        }
        mpos += width;
      }
    };
    for (const pieces of spans) {
      const out = { text: "" };
      const before = mpos;
      // The line break comes before the span; it is undone if the span is dropped.
      if (parts.length > 0) {
        mpos += 1;
      }
      emit(pieces, out);
      if (out.text.trim() === "") {
        // The span was dropped: nothing of it counts.
        mpos = before;
        while ((clauseSegments.at(-1)?.maskedStart ?? -1) >= before) {
          clauseSegments.pop();
        }
        continue;
      }
      parts.push(out.text);
    }
    segments.set(clause.id, clauseSegments);
    if (parts.length > 0) {
      masked.push({ id: clause.id, text: parts.join("\n") });
    }
  }
  return {
    clauses: viewClauses,
    placeholders,
    mapping,
    masked,
    acknowledged: outermost(acknowledged),
    segments,
  };
}

export function viewOf(review: Review): View {
  let view = VIEWS.get(review);
  if (view === undefined) {
    view = buildView(review);
    VIEWS.set(review, view);
  }
  return view;
}

/* ------------------------------------------------------------------------------------------ */
/* Public API                                                                                   */
/* ------------------------------------------------------------------------------------------ */

export function startReview(segmentation: Segmentation, label: string): Review {
  return {
    label,
    detectorVersion: segmentation.detectorVersion,
    segmentation,
    entities: segmentation.entities.map((entity) => ({
      id: entity.id,
      cls: entity.cls,
      precision: entity.precision,
      manual: false,
      occurrences: entity.spans.map((span) => ({ span, masked: true })),
    })),
    manualCount: 0,
  };
}

/** The same review under another label (a contract before it was removed). */
export function relabel(review: Review, label: string): Review {
  return review.label === label ? review : { ...review, label };
}

function entityIndex(review: Review, id: string): number {
  return review.entities.findIndex((entity) => entity.id === id);
}

export function placeholderOf(review: Review, entityId: string): string | null {
  return viewOf(review).placeholders[entityIndex(review, entityId)] ?? null;
}

export function mappingOf(review: Review): ReadonlyMap<string, string> {
  return viewOf(review).mapping;
}

export function maskedClauses(review: Review): readonly MaskedClause[] {
  return viewOf(review).masked;
}

/** Clause-relative spans of the unmasked occurrences of detected entities, sorted. */
export function acknowledgedUnmasked(review: Review): readonly ClauseSpan[] {
  return viewOf(review).acknowledged;
}

/** Detected `normal` entities may be unmasked, except checksummed codes. Own masks always. */
export function canUnmask(review: Review, entityId: string): boolean {
  const entity = review.entities[entityIndex(review, entityId)];
  if (entity === undefined) {
    return false;
  }
  return entity.manual || (entity.precision === "normal" && !CODE_CLASSES.has(entity.cls));
}

function replaceEntity(
  review: Review,
  index: number,
  change: (entity: ReviewEntity) => ReviewEntity,
): Review {
  return {
    ...review,
    entities: review.entities.map((entity, i) => (i === index ? change(entity) : entity)),
  };
}

export function unmaskEntity(review: Review, entityId: string): Review {
  const index = entityIndex(review, entityId);
  if (!canUnmask(review, entityId)) {
    return review;
  }
  return replaceEntity(review, index, (entity) => ({
    ...entity,
    occurrences: entity.occurrences.map(({ span }) => ({ span, masked: false })),
  }));
}

export function unmaskOccurrence(review: Review, entityId: string, occurrence: number): Review {
  const index = entityIndex(review, entityId);
  const target = review.entities[index]?.occurrences[occurrence];
  if (!canUnmask(review, entityId) || target === undefined) {
    return review;
  }
  return replaceEntity(review, index, (entity) => ({
    ...entity,
    occurrences: entity.occurrences.map((item, i) =>
      i === occurrence ? { span: item.span, masked: false } : item,
    ),
  }));
}

/* --- selection ------------------------------------------------------------------------------ */

const WORD = /[\p{L}\p{N}]/u;

function overlaps(a: Span, b: Span): boolean {
  return a[0] === b[0] && a[1] < b[2] && b[1] < a[2];
}

function sameSpan(a: Span, b: Span): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

/** Whether the span lies inside one span of one clause (so that it is part of a clause text). */
function insideClause(review: Review, span: Span): boolean {
  return review.segmentation.clauses.some((clause) =>
    clause.spans.some((s) => s[0] === span[0] && s[1] <= span[1] && span[2] <= s[2]),
  );
}

/** An unmasked occurrence with exactly this span, if there is one. */
function plainOccurrence(review: Review, span: Span): [number, number] | null {
  for (const [entity, item] of review.entities.entries()) {
    for (const [index, occurrence] of item.occurrences.entries()) {
      if (!occurrence.masked && sameSpan(occurrence.span, span)) {
        return [entity, index];
      }
    }
  }
  return null;
}

/**
 * Whether the span can get a new mask: it is non-empty, lies inside a clause and touches no
 * occurrence of any entity, except that an unmasked occurrence of exactly this span is masked
 * again. A part of an entity is refused: a split mask could leave a name readable.
 */
export function maskable(review: Review, span: Span): boolean {
  const block = review.segmentation.blocks[span[0]];
  if (block === undefined || span[2] <= span[1] || span[2] > blockLength(block)) {
    return false;
  }
  if (!insideClause(review, span)) {
    return false;
  }
  if (plainOccurrence(review, span) !== null) {
    return true;
  }
  return !review.entities.some((entity) =>
    entity.occurrences.some((occurrence) => overlaps(occurrence.span, span)),
  );
}

/** Every text in the document equal to the text of `span`, including `span` itself. */
export function equalOccurrences(review: Review, span: Span): Span[] {
  const { blocks } = review.segmentation;
  const needle = spanText(blocks, span);
  if (needle === "") {
    return [];
  }
  const first = needle.charAt(0);
  const last = needle.charAt(needle.length - 1);
  const out: Span[] = [];
  const length = cpLength(needle);
  for (const [index, block] of blocks.entries()) {
    for (
      let at = block.text.indexOf(needle);
      at >= 0;
      at = block.text.indexOf(needle, at + needle.length)
    ) {
      const before = at > 0 ? block.text.charAt(at - 1) : "";
      const after = block.text.charAt(at + needle.length);
      // A word is not found inside a longer word.
      const edge =
        (WORD.test(first) && before !== "" && WORD.test(before)) ||
        (WORD.test(last) && after !== "" && WORD.test(after));
      const start = codePointOffset(block, at);
      if (!edge || (index === span[0] && start === span[1])) {
        out.push([index, start, start + length]);
      }
    }
  }
  if (!out.some((found) => sameSpan(found, span))) {
    out.push(span);
    out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  }
  return out;
}

function maskAgain(review: Review, entity: number, index: number, premasked: boolean): Review {
  return replaceEntity(review, entity, (item) => ({
    ...item,
    occurrences: item.occurrences.map((occurrence, i) =>
      i === index
        ? premasked
          ? { span: occurrence.span, masked: true, premasked: true }
          : { span: occurrence.span, masked: true }
        : occurrence,
    ),
  }));
}

function addManual(
  review: Review,
  cls: EntityClass,
  spans: readonly Span[],
  premasked: boolean,
): Review {
  const count = review.manualCount + 1;
  return {
    ...review,
    manualCount: count,
    entities: [
      ...review.entities,
      {
        id: `m${String(count)}`,
        cls,
        precision: "normal",
        manual: true,
        occurrences: spans.map((span) =>
          premasked ? { span, masked: true, premasked: true } : { span, masked: true },
        ),
      },
    ],
  };
}

function maskSpans(
  review: Review,
  spans: readonly Span[],
  cls: string,
  premasked: boolean,
): Review {
  if (!CLASS_SET.has(cls)) {
    return review;
  }
  let next = review;
  const fresh: Span[] = [];
  for (const span of spans) {
    if (!maskable(next, span)) {
      continue;
    }
    const known = plainOccurrence(next, span);
    if (known !== null) {
      next = maskAgain(next, known[0], known[1], premasked);
    } else {
      fresh.push(span);
    }
  }
  return fresh.length === 0 ? next : addManual(next, cls as EntityClass, fresh, premasked);
}

/** Masks only this span with `cls`. Refused (same review) for an unknown class or a bad span. */
export function maskSelection(review: Review, span: Span, cls: string): Review {
  return maskSpans(review, [span], cls, false);
}

/** Masks this span and every equal text of the document under one placeholder. */
export function maskAllEqual(review: Review, span: Span, cls: string): Review {
  return maskSpans(review, equalOccurrences(review, span), cls, false);
}

/** How many texts `maskAllEqual` would mask. */
export function countMaskable(review: Review, span: Span): number {
  return equalOccurrences(review, span).filter((found) => maskable(review, found)).length;
}

/* --- server answer -------------------------------------------------------------------------- */

/**
 * Masks the spans that the safety check found unmasked. Spans are clause-relative offsets
 * into the MASKED clause text. An unmasked occurrence they touch is masked again;
 * any other text gets a manual mask. Everything touched is marked for a new confirmation.
 */
export function applyUnmaskedIdentifiers(review: Review, spans: readonly ClauseSpan[]): Review {
  let next = review;
  for (const [clauseId, start, end] of spans) {
    const segments = viewOf(next).segments.get(clauseId);
    if (segments === undefined) {
      continue;
    }
    const first = segments.find((s) => s.maskedStart <= start && start < s.maskedEnd);
    if (first === undefined || first.masked) {
      continue;
    }
    const last = segments.find((s) => s.maskedStart < end && end <= s.maskedEnd);
    const stop = last?.block === first.block ? last : first;
    const to = Math.min(end, stop.maskedEnd) - stop.maskedStart + stop.start;
    const block = next.segmentation.blocks[first.block];
    if (block === undefined) {
      continue;
    }
    const target: Span = [first.block, start - first.maskedStart + first.start, to];
    // Every unmasked occurrence the span touches is masked again, whole.
    const touched: [number, number][] = [];
    for (const [entity, item] of next.entities.entries()) {
      for (const [index, occurrence] of item.occurrences.entries()) {
        if (!occurrence.masked && overlaps(occurrence.span, target)) {
          touched.push([entity, index]);
        }
      }
    }
    if (touched.length > 0) {
      for (const [entity, index] of touched) {
        next = maskAgain(next, entity, index, true);
      }
    } else if (maskable(next, target)) {
      next = addManual(next, PREMASK_CLASS, [target], true);
    }
  }
  return next;
}

/**
 * The server spans that cannot be mapped back to the contract text: an unknown clause, or a
 * start inside a placeholder or outside any text. They are never dropped silently: the caller
 * shows an error and the contract stays not ready.
 */
export function unmappedSpans(review: Review, spans: readonly ClauseSpan[]): ClauseSpan[] {
  const segments = viewOf(review).segments;
  return spans.filter(([clauseId, start]) => {
    const found = segments
      .get(clauseId)
      ?.find((s) => s.maskedStart <= start && start < s.maskedEnd);
    return found === undefined || found.masked;
  });
}

/* --- DOM positions -------------------------------------------------------------------------- */

/** A position in a block, in code points. */
export interface BlockPosition {
  readonly block: number;
  readonly offset: number;
}

/** The block position of a UTF-16 offset inside a text piece. */
export function positionInPiece(
  review: Review,
  piece: Extract<Piece, { kind: "text" }>,
  unit: number,
): BlockPosition | null {
  const block = review.segmentation.blocks[piece.block];
  if (block === undefined || piece.block < 0) {
    return null;
  }
  const base = unitOffset(block, piece.start);
  return { block: piece.block, offset: codePointOffset(block, base + unit) };
}

/** Trims white space at both ends of a span (a selection often has some). */
export function trimSpan(review: Review, span: Span): Span {
  const block = review.segmentation.blocks[span[0]];
  if (block === undefined) {
    return span;
  }
  const from = unitOffset(block, span[1]);
  const to = unitOffset(block, span[2]);
  const raw = block.text.slice(from, to);
  const lead = raw.length - raw.trimStart().length;
  const body = raw.trim();
  if (body === "") {
    return [span[0], span[1], span[1]];
  }
  const start = codePointOffset(block, from + lead);
  return [span[0], start, start + cpLength(body)];
}

/** The original text of one occurrence (plain text). */
export function occurrenceText(review: Review, span: Span): string {
  return spanText(review.segmentation.blocks, span);
}
