# ruff: noqa: RUF001
"""The detector: cleaned blocks and clauses in, entities and decisions out (ADR 0015).

Pure and deterministic. The caps (5,000 entities, 50,000 spans) are checked while the hits
are collected. Pipeline: matching view, placeholder look-alikes, contacts, line rules,
names; then overlaps are resolved on the cleaned text, hits are grouped into entities by
(class, key), the requisites section is decided line by line, and clause warnings are made.
Nothing here logs or returns a value string.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.pseudo import contacts, lines
from app.pseudo.hits import (
    ADDRESS,
    CLASS_ORDER,
    HIGH,
    MAX_ENTITIES,
    MAX_SPANS,
    NORMAL,
    ORG,
    SIGNATURE,
    Hit,
    Hits,
    TooManyIdentifiersError,
)
from app.pseudo.lexicon import (
    AMOUNT_WORDS,
    REQUISITES_LABELS,
    is_obligation,
    is_role,
)
from app.pseudo.lines import amount_or_date_follows
from app.pseudo.matching import View, build_view, fold
from app.pseudo.names import Names
from app.pseudo.tables import CURRENCY_SIGNS
from app.segment.model import Clause, LineAction

__all__ = ["DetectedEntity", "Detection", "TooManyIdentifiersError", "detect"]

_LOOKALIKE: Final = re.compile(r"\[(?:[A-Z]\.)?[A-Z_]{2,16}_[0-9]{1,5}\]")
_AMOUNT_AFTER: Final = re.compile(r"[0-9](?:[0-9]|[ .,](?=[0-9])){0,20} ?(?:%|[^\W\d_]{1,12})")
_WORD: Final = re.compile(r"[^\W_]+")
_PUNCTUATION: Final = frozenset(" \t.,:;—–-/\\()[]{}«»\"'“”„_|*•·+")
_NEAR: Final = 40
_MIN_PIECE: Final = 4
_CLASS_RANK: Final = {name: index for index, name in enumerate(CLASS_ORDER)}
_BRACKETS: Final = {"[": "⟦", "]": "⟧"}
_LOOKALIKE_WARNING: Final = "placeholder_lookalike"
_AMOUNT_WARNING: Final = "masked_next_to_amount"
_REQUISITES_WARNING: Final = "requisites_condition"


@dataclass(slots=True)
class DetectedEntity:
    id: str
    cls: str
    precision: str
    spans: list[tuple[int, int, int]]


@dataclass(slots=True)
class Detection:
    texts: list[str]
    entities: list[DetectedEntity] = field(default_factory=list)
    requisites: list[tuple[str, list[tuple[tuple[int, int, int], LineAction]]]] = field(
        default_factory=list
    )
    neutralized: list[tuple[int, int, int]] = field(default_factory=list)
    warnings: list[tuple[str, str | None]] = field(default_factory=list)


class _ClauseIndex:
    """Clause of a block position."""

    def __init__(self, clauses: Sequence[Clause], blocks: int) -> None:
        self.starts: list[list[int]] = [[] for _ in range(blocks)]
        self.ends: list[list[int]] = [[] for _ in range(blocks)]
        self.ids: list[list[str]] = [[] for _ in range(blocks)]
        entries: list[list[tuple[int, int, str]]] = [[] for _ in range(blocks)]
        for clause in clauses:
            for block, start, end in clause.spans:
                entries[block].append((start, end, clause.id))
        for block, items in enumerate(entries):
            items.sort()
            self.starts[block] = [item[0] for item in items]
            self.ends[block] = [item[1] for item in items]
            self.ids[block] = [item[2] for item in items]

    def find(self, block: int, offset: int) -> str | None:
        index = bisect_right(self.starts[block], offset) - 1
        if index >= 0 and offset < self.ends[block][index]:
            return self.ids[block][index]
        return None

    def split(self, block: int, start: int, end: int) -> list[tuple[int, int, int]]:
        """``(block, start, end)`` cut at the borders of the clause spans it crosses.

        A line break inside a block can start a new clause ("\\n12. ..."); a mask must not
        cross that border, or the review cannot place it. Text outside every clause span
        (a break between two clauses) is dropped; a piece outside all of them is kept.
        """
        starts, ends = self.starts[block], self.ends[block]
        found: list[tuple[int, int, int]] = []
        i = max(0, bisect_right(starts, start) - 1)
        while i < len(starts) and starts[i] < end:
            lo, hi = max(start, starts[i]), min(end, ends[i])
            if lo < hi and (not found or found[-1][2] <= lo):
                found.append((block, lo, hi))
            i += 1
        return found or [(block, start, end)]


def detect(texts: Sequence[str], clauses: Sequence[Clause]) -> Detection:
    index = _ClauseIndex(clauses, len(texts))
    view = build_view(list(texts), index.find)
    result = Detection(list(texts))
    _neutralize(view, result, index)
    requisites = _requisites_ranges(view, clauses)
    hits = Hits()
    contacts.scan_all(view.low, hits)
    same, other = _same_clause(view, index)
    lines.scan_lines(view, hits, _in_ranges(view, requisites), same, other)
    names = Names(view, hits)
    names.pass_one()
    names.pass_two()
    accepted = _resolve(view, hits.items)
    entities = _group(view, accepted, index)
    result.entities = entities
    _warn_amounts(view, accepted, index, result)
    _decide_requisites(view, clauses, entities, index, result)
    return result


# ---------------------------------------------------------------- look-alikes


def _neutralize(view: View, result: Detection, index: _ClauseIndex) -> None:
    skeleton = view.s
    replace: dict[int, str] = {}
    position = skeleton.find("[")
    warned: set[str] = set()
    while position != -1:
        matched = _LOOKALIKE.match(skeleton, position)
        if matched is not None:
            first = view.g_start(position)
            last = view.g_end(matched.end()) - 1
            replace[first] = "⟦"
            replace[last] = "⟧"
            for block, start, end in view.g_pieces(first, last + 1):
                result.neutralized.append((block, start, end))
                clause = index.find(block, start)
                if (clause or "") not in warned:
                    warned.add(clause or "")
                    result.warnings.append((_LOOKALIKE_WARNING, clause))
            position = skeleton.find("[", matched.end())
        else:
            position = skeleton.find("[", position + 1)
    if replace:
        result.texts = _apply_replacements(view, result.texts, replace)


def _apply_replacements(view: View, texts: list[str], replace: dict[int, str]) -> list[str]:
    per_block: dict[int, list[tuple[int, str]]] = {}
    for gpos, char in replace.items():
        block = bisect_right(view.bases, gpos) - 1
        per_block.setdefault(block, []).append((gpos - view.bases[block], char))
    updated = list(texts)
    for block, items in per_block.items():
        chars = list(updated[block])
        for offset, char in items:
            if offset < len(chars) and chars[offset] in "[]［］":
                chars[offset] = char
        updated[block] = "".join(chars)
    return updated


# ------------------------------------------------------------------ requisites


def _requisites_ranges(view: View, clauses: Sequence[Clause]) -> tuple[list[int], list[int]]:
    ranges = sorted(
        (view.bases[block] + start, view.bases[block] + end)
        for clause in clauses
        if clause.section_kind == "requisites"
        for block, start, end in clause.spans
    )
    starts: list[int] = []
    ends: list[int] = []
    for start, end in ranges:
        if ends and start <= ends[-1]:
            ends[-1] = max(ends[-1], end)
        else:
            starts.append(start)
            ends.append(end)
    return starts, ends


def _in_ranges(view: View, ranges: tuple[list[int], list[int]]) -> Callable[[int], bool]:
    starts, ends = ranges

    def inside(position: int) -> bool:
        if not starts:
            return False
        g = view.g_start(position)
        index = bisect_right(starts, g) - 1
        return index >= 0 and g < ends[index]

    return inside


def _same_clause(
    view: View, index: _ClauseIndex
) -> tuple[Callable[[int, int], bool], Callable[[int, int], bool]]:
    """``same(a, b)``: both positions are in one clause; ``other(a, b)``: both are in
    clauses, and in different ones."""

    def clause_at(position: int) -> str | None:
        g = view.g_start(position)
        block = bisect_right(view.bases, g) - 1
        return index.find(block, g - view.bases[block])

    def same(first: int, second: int) -> bool:
        clause = clause_at(first)
        return clause is not None and clause == clause_at(second)

    def other(first: int, second: int) -> bool:
        one, two = clause_at(first), clause_at(second)
        return one is not None and two is not None and one != two

    return same, other


# --------------------------------------------------------------------- resolve


@dataclass(slots=True)
class _Accepted:
    cls: str
    precision: str
    key: str
    gs: int
    ge: int
    hit: Hit | None


def _is_container(hit: Hit) -> bool:
    return hit.cls == SIGNATURE or (hit.cls == ORG and hit.key.startswith("fop:"))


def _resolve(view: View, items: list[Hit]) -> list[_Accepted]:
    size = len(view.g)
    taken = bytearray(size + 1)
    nested = bytearray(size + 1)
    order = sorted(
        (
            (
                hit.precision != HIGH,
                -(view.g_end(hit.end) - view.g_start(hit.start)),
                _CLASS_RANK[hit.cls],
                view.g_start(hit.start),
                hit,
            )
            for hit in items
        ),
        key=lambda item: item[:4],
    )
    accepted: list[_Accepted] = []
    for _, _, _, _, hit in order:
        gs, ge = view.g_start(hit.start), view.g_end(hit.end)
        layer = nested if _is_container(hit) else taken
        if any(layer[gs:ge]):
            if hit.cls == ADDRESS:
                accepted.extend(_address_pieces(view, hit, gs, ge, layer))
            continue
        layer[gs:ge] = b"\x01" * (ge - gs)
        accepted.append(_Accepted(hit.cls, hit.precision, hit.key, gs, ge, hit))
    return accepted


def _address_pieces(view: View, hit: Hit, gs: int, ge: int, layer: bytearray) -> list[_Accepted]:
    """The parts of an address that no other hit took."""
    pieces: list[_Accepted] = []
    cursor = gs
    count = 0
    while cursor < ge:
        if layer[cursor]:
            cursor += 1
            continue
        end = cursor
        while end < ge and not layer[end]:
            end += 1
        start, stop = cursor, end
        while start < stop and view.g[start] in " ,:;":
            start += 1
        while stop > start and view.g[stop - 1] in " ,:;":
            stop -= 1
        if stop - start >= _MIN_PIECE and any(c.isalnum() for c in view.g[start:stop]):
            layer[start:stop] = b"\x01" * (stop - start)
            count += 1
            pieces.append(_Accepted(ADDRESS, NORMAL, f"{hit.key}#{count}", start, stop, None))
        cursor = end
    return pieces


# ----------------------------------------------------------------------- group


def _group(view: View, accepted: list[_Accepted], index: _ClauseIndex) -> list[DetectedEntity]:
    groups: dict[tuple[str, str], list[_Accepted]] = {}
    spans_total = 0
    for item in accepted:
        groups.setdefault((item.cls, item.key), []).append(item)
        if len(groups) > MAX_ENTITIES:
            raise TooManyIdentifiersError
    ordered = sorted(groups.values(), key=lambda items: min(i.gs for i in items))
    entities: list[DetectedEntity] = []
    for number, items in enumerate(ordered, start=1):
        items.sort(key=lambda i: (i.gs, i.ge))
        spans: list[tuple[int, int, int]] = []
        for item in items:
            for block, start, end in view.g_pieces(item.gs, item.ge):
                spans.extend(index.split(block, start, end))
        spans_total += len(spans)
        if spans_total > MAX_SPANS:
            raise TooManyIdentifiersError
        precision = HIGH if any(i.precision == HIGH for i in items) else NORMAL
        entities.append(DetectedEntity(f"e{number}", items[0].cls, precision, spans))
    return entities


# --------------------------------------------------------------------- amounts


def _warn_amounts(
    view: View, accepted: list[_Accepted], index: _ClauseIndex, result: Detection
) -> None:
    low = view.low
    warned: set[str] = set()
    for item in accepted:
        hit = item.hit
        if hit is None or not _next_to_amount(low, hit.start, hit.end):
            continue
        block = bisect_right(view.bases, item.gs) - 1
        clause = index.find(block, item.gs - view.bases[block])
        key = clause or ""
        if key not in warned:
            warned.add(key)
            result.warnings.append((_AMOUNT_WARNING, clause))


def _next_to_amount(low: str, start: int, end: int) -> bool:
    """A number with a currency, unit or percent sign touches the entity."""
    after = low[end : end + _NEAR].lstrip(" ")
    if after[:1].isdigit():
        matched = _AMOUNT_AFTER.match(after)
        if matched is not None:
            tail = matched.group()
            if tail.endswith("%") or _last_word(tail) in AMOUNT_WORDS:
                return True
    before = low[max(0, start - _NEAR) : start].rstrip(" ")
    if before and (before[-1] in CURRENCY_SIGNS or _last_word(before) in AMOUNT_WORDS):
        word = _last_word(before)
        prefix = before[: len(before) - len(word)].rstrip(" ") if word else before[:-1].rstrip(" ")
        return prefix[-1:].isdigit()
    return False


def _last_word(text: str) -> str:
    index = len(text)
    while index > 0 and text[index - 1].isalpha():
        index -= 1
    return text[index:]


# ------------------------------------------------------------------ requisites


def _decide_requisites(
    view: View,
    clauses: Sequence[Clause],
    entities: list[DetectedEntity],
    index: _ClauseIndex,
    result: Detection,
) -> None:
    targets = [clause for clause in clauses if clause.section_kind == "requisites"]
    if not targets:
        return
    mask = bytearray(len(view.g) + 1)
    for entity in entities:
        for block, start, end in entity.spans:
            base = view.bases[block]
            mask[base + start : base + end] = b"\x01" * (end - start)
    for clause in targets:
        decided: list[tuple[tuple[int, int, int], LineAction]] = []
        for block, start, end in clause.spans:
            decided.extend(_decide_span(view, clause, block, start, end, mask))
        result.requisites.append((clause.id, decided))
        if any(action == "keep" for _, action in decided):
            result.warnings.append((_REQUISITES_WARNING, clause.id))


def _decide_span(  # noqa: PLR0913, PLR0917
    view: View, clause: Clause, block: int, start: int, end: int, mask: bytearray
) -> list[tuple[tuple[int, int, int], LineAction]]:
    text = view.g
    base = view.bases[block]
    decided: list[tuple[tuple[int, int, int], LineAction]] = []
    position = start
    while position <= end:
        newline = text.find("\n", base + position, base + end)
        line_end = end if newline < 0 else newline - base
        first, last = position, line_end
        while first < last and text[base + first].isspace():
            first += 1
        while last > first and text[base + last - 1].isspace():
            last -= 1
        if first < last and not _is_heading(clause, block, first, last):
            action: LineAction = (
                "drop" if _droppable(text, base + first, base + last, mask) else "keep"
            )
            decided.append(((block, first, last), action))
        position = line_end + 1
    return decided


def _is_heading(clause: Clause, block: int, first: int, last: int) -> bool:
    heading = clause.heading_span
    return (
        heading is not None and heading[0] == block and first <= heading[1] and heading[2] <= last
    )


def _has_condition(line: str) -> bool:
    """An amount, a percent, a date, a unit or an obligation marker is in the line.

    ``line`` is the folded text of the whole line; masked characters count too, so a mask
    cannot hide a condition from the check.
    """
    position = 0
    size = len(line)
    while position < size:
        if line[position] in CURRENCY_SIGNS:
            return True
        matched = _WORD.match(line, position)
        if matched is None:
            position += 1
            continue
        end = matched.end()
        word = line[position:end]
        if word.isdigit():
            if amount_or_date_follows(line, position, end, size):
                return True
        elif is_obligation(word) and word not in REQUISITES_LABELS:
            return True
        position = end
    return False


def _droppable(text: str, first: int, last: int, mask: bytearray) -> bool:
    """No condition in the line; every letter and digit is in an entity, a label or a role."""
    if _has_condition(fold(text[first:last])):
        return False
    position = first
    while position < last:
        char = text[position]
        if mask[position] or char in _PUNCTUATION or char.isspace():
            position += 1
            continue
        matched = _WORD.match(text, position, last)
        if matched is None:
            return False
        end = matched.end()
        if not all(mask[position:end]):
            word = fold(text[position:end])
            if is_obligation(word) or not (word in REQUISITES_LABELS or is_role(word)):
                return False
        position = end
    return True
