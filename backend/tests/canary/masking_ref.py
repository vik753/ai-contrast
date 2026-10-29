"""Browser-equivalent masking in Python (ADR 0015 points 3 and 6).

A line-by-line port of the review logic of ``frontend/src/pseudo/masking.ts``
(``buildView``) for the cases the canary harness needs: detected entities, unmask
decisions, requisites ``drop``/``keep`` lines and neutralized look-alikes. Manual masks
are not modelled. The shared vectors in ``shared/pseudo-vectors.json`` run through both
this module and the TypeScript code; they must agree.

Input is the wire reply of ``POST /api/segment`` (dict). Offsets are code points, which
are Python string indexes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Span = tuple[int, int, int]
CODE_CLASSES = frozenset({"TAX_ID", "ACCOUNT"})


@dataclass
class Occurrence:
    span: Span
    masked: bool = True


@dataclass
class Entity:
    id: str
    cls: str
    precision: str
    occurrences: list[Occurrence]


@dataclass
class Review:
    label: str
    seg: dict[str, Any]
    entities: list[Entity] = field(default_factory=list)


@dataclass
class Masked:
    clauses: list[dict[str, str]]
    acknowledged: list[list[Any]]
    mapping: dict[str, str]


def start_review(seg: dict[str, Any], label: str) -> Review:
    entities = [
        Entity(
            e["id"],
            e["class"],
            e["precision"],
            [Occurrence((s[0], s[1], s[2])) for s in e["spans"]],
        )
        for e in seg.get("entities", [])
    ]
    return Review(label, seg, entities)


def can_unmask(entity: Entity) -> bool:
    return entity.precision == "normal" and entity.cls not in CODE_CLASSES


def unmask_entity(review: Review, entity_id: str) -> None:
    for entity in review.entities:
        if entity.id == entity_id and can_unmask(entity):
            for occ in entity.occurrences:
                occ.masked = False


def unmask_occurrence(review: Review, entity_id: str, index: int) -> None:
    for entity in review.entities:
        if entity.id == entity_id and can_unmask(entity) and index < len(entity.occurrences):
            entity.occurrences[index].masked = False


@dataclass
class _Annot:
    start: int
    end: int
    kind: str  # mask | plain | neutral
    entity: int
    index: int


def _order(a: _Annot) -> tuple[int, int]:
    return (a.start, -a.end)


def _annotations(review: Review) -> dict[int, list[_Annot]]:
    masked: dict[int, list[_Annot]] = {}
    others: dict[int, list[_Annot]] = {}
    for ei, entity in enumerate(review.entities):
        for oi, occ in enumerate(entity.occurrences):
            block, start, end = occ.span
            target = masked if occ.masked else others
            target.setdefault(block, []).append(
                _Annot(start, end, "mask" if occ.masked else "plain", ei, oi)
            )
    for span in review.seg.get("neutralized", []):
        others.setdefault(span[0], []).append(_Annot(span[1], span[2], "neutral", -1, -1))
    result: dict[int, list[_Annot]] = {}
    for block in sorted(set(masked) | set(others)):
        chosen: list[_Annot] = []
        last = 0
        for annot in sorted(masked.get(block, []), key=_order):
            if annot.start >= last:
                chosen.append(annot)
                last = annot.end
        free: list[_Annot] = []
        at = 0
        for annot in sorted(others.get(block, []), key=_order):
            while at < len(chosen) and chosen[at].end <= annot.start:
                at += 1
            clash = at < len(chosen) and chosen[at].start < annot.end
            if not clash and (not free or annot.start >= free[-1].end):
                free.append(annot)
        allv = sorted(chosen + free, key=_order)
        if allv:
            result[block] = allv
    return result


def _within(annots: list[_Annot] | None, lo: int, hi: int) -> list[_Annot]:
    return [a for a in (annots or []) if a.start >= lo and a.end <= hi and a.start < hi]


@dataclass
class _Piece:
    kind: str  # text | mark | line
    text: str = ""
    entity: int = -1
    occ_entity: int = -1  # plain occurrence of an entity
    action: str = ""
    children: list[_Piece] = field(default_factory=list)


class _Emitter:
    """Walks the pieces of one clause: masked text, offsets in it, acknowledged spans."""

    def __init__(self, clause_id: str, assign: Callable[[int, str], str]) -> None:
        self.clause_id = clause_id
        self.assign = assign
        self.mpos = 0
        self.ack: list[list[Any]] = []

    def emit(self, items: list[_Piece], out: list[str]) -> None:
        for piece in items:
            if piece.kind == "line":
                if piece.action == "keep":
                    self.emit(piece.children, out)
                continue
            shown = self.assign(piece.entity, piece.text) if piece.kind == "mark" else piece.text
            out.append(shown)
            if piece.kind == "text" and piece.occ_entity >= 0:
                self.ack.append([self.clause_id, self.mpos, self.mpos + len(piece.text)])
            self.mpos += len(shown)


def _outermost(spans: list[list[Any]]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for span in spans:
        if out and out[-1][0] == span[0] and span[1] < out[-1][2]:
            continue
        out.append(span)
    return out


def mask_review(review: Review) -> Masked:  # noqa: PLR0915 - a port of one function
    seg = review.seg
    blocks = [b["text"] for b in seg["blocks"]]
    annots = _annotations(review)
    lines_of: dict[str, list[dict[str, Any]]] = {}
    for item in seg.get("requisites", []):
        lines_of.setdefault(item["clause"], []).extend(item["lines"])

    def text(block: int, start: int, end: int) -> list[_Piece]:
        return [_Piece("text", blocks[block][start:end])] if end > start else []

    def inner(block: int, lo: int, hi: int) -> list[_Piece]:
        pieces: list[_Piece] = []
        cursor = lo
        for annot in _within(annots.get(block), lo, hi):
            if annot.start < cursor:
                continue
            pieces.extend(text(block, cursor, annot.start))
            original = blocks[block][annot.start : annot.end]
            if annot.kind == "mask":
                pieces.append(_Piece("mark", original, entity=annot.entity))
            elif annot.kind == "neutral":
                pieces.append(_Piece("text", original))
            else:
                pieces.append(_Piece("text", original, occ_entity=annot.entity))
            cursor = annot.end
        pieces.extend(text(block, cursor, hi))
        return pieces

    placeholders: list[str | None] = [None for _ in review.entities]
    counters: dict[str, int] = {}
    mapping: dict[str, str] = {}
    masked: list[dict[str, str]] = []
    acknowledged: list[list[Any]] = []

    def assign(entity: int, original: str) -> str:
        known = placeholders[entity]
        if known is not None:
            return known
        cls = review.entities[entity].cls
        counters[cls] = counters.get(cls, 0) + 1
        placeholder = f"[{review.label}.{cls}_{counters[cls]}]"
        placeholders[entity] = placeholder
        mapping[placeholder] = original
        return placeholder

    for clause in seg["clauses"]:
        lines = lines_of.get(clause["id"], [])
        span_pieces: list[list[_Piece]] = []
        for block, lo, hi in clause["spans"]:
            mine = sorted(
                (
                    (ln["span"][1], ln["span"][2], ln["action"])
                    for ln in lines
                    if ln["span"][0] == block
                    and ln["span"][1] >= lo
                    and ln["span"][2] <= hi
                    and ln["span"][2] > ln["span"][1]
                ),
                key=lambda x: x[0],
            )
            pieces: list[_Piece] = []
            cursor = lo
            for start, end, action in mine:
                if start < cursor:
                    continue
                pieces.extend(inner(block, cursor, start))
                unmasked_inside = any(
                    a.kind == "plain" for a in _within(annots.get(block), start, end)
                )
                pieces.append(
                    _Piece(
                        "line",
                        action="drop" if action == "drop" and not unmasked_inside else "keep",
                        children=inner(block, start, end),
                    )
                )
                cursor = end
            pieces.extend(inner(block, cursor, hi))
            span_pieces.append(pieces)

        parts: list[str] = []
        emitter = _Emitter(clause["id"], assign)
        for pieces in span_pieces:
            before, ack_before = emitter.mpos, len(emitter.ack)
            if parts:
                emitter.mpos += 1
            out: list[str] = []
            emitter.emit(pieces, out)
            joined = "".join(out)
            if joined.strip() == "":
                emitter.mpos = before
                del emitter.ack[ack_before:]
                continue
            parts.append(joined)
        clause_ack = emitter.ack
        acknowledged.extend(clause_ack)
        if parts:
            masked.append({"id": clause["id"], "text": "\n".join(parts)})
    return Masked(masked, _outermost(acknowledged), mapping)


def mask_segmentation(
    seg: dict[str, Any],
    label: str = "A",
    *,
    unmask: list[str] | None = None,
    unmask_occurrences: list[tuple[str, int]] | None = None,
) -> Masked:
    review = start_review(seg, label)
    for entity_id in unmask or []:
        unmask_entity(review, entity_id)
    for entity_id, index in unmask_occurrences or []:
        unmask_occurrence(review, entity_id, index)
    return mask_review(review)
