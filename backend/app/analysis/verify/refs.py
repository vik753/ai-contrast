# ruff: noqa: RUF001, RUF002
"""Clause references and cross-reference closure (ADR 0019 point 4). Depth 1, linear.

A number is a reference after a prefix word ("clause", "п."), after a joiner that follows a
reference ("clauses 4.1 and 4.2"), or, when dotted, when it equals an existing clause number.
A range ("4.1-4.3", "з 4.1 по 4.3") stands for every existing clause number inside it.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from app.analysis.verify.lexicon import LANGS, LEXICON
from app.analysis.verify.model import Clause, ClosureEntry
from app.analysis.verify.text import normalize, span_to_source

__all__ = ["Reference", "covers", "find_references", "number_key", "reference_closure"]

_NUMBER: Final = re.compile(r"\d+(?:\.\d+)*")
_WINDOW: Final = 40
_MAX_GAP: Final = 12
_MAX_NUMBER: Final = 40
_LEADING: Final = "([«\"'“"


def _set(words: dict[str, tuple[str, ...]]) -> frozenset[str]:
    return frozenset(normalize(w)[0] for lang in LANGS for w in words[lang])


_PREFIXES: Final = _set(LEXICON.ref_prefixes)
_JOINERS: Final = _set(LEXICON.ref_joiners)
_FROM: Final = frozenset(normalize(w)[0] for w in ("з", "с", "from"))
_RANGE_WORDS: Final = frozenset(normalize(w)[0] for w in ("-", "to", "through", "по", "до"))
_RANGE_GAP: Final = _JOINERS | _RANGE_WORDS | _FROM


@dataclass(frozen=True, slots=True)
class Reference:
    """A clause number, or a range ``low`` to ``high``, with source offsets."""

    low: str
    high: str | None
    start: int
    end: int


def number_key(number: str) -> tuple[int, ...] | None:
    """``"4.2"`` as ``(4, 2)``; ``None`` for anything else."""
    if not number or len(number) > _MAX_NUMBER:
        return None
    try:
        return tuple(int(part) for part in number.split("."))
    except ValueError:
        return None


def covers(ref: Reference, number: str) -> bool:
    """Does the reference name the clause number?"""
    if ref.high is None:
        return ref.low == number
    low, high, key = number_key(ref.low), number_key(ref.high), number_key(number)
    return low is not None and high is not None and key is not None and low <= key <= high


def _gap_tokens(view: str, a: int, b: int) -> list[str] | None:
    if b - a > _MAX_GAP:
        return None
    tokens = view[a:b].replace(",", " , ").replace("-", " - ").split()
    return tokens if tokens and all(t in _RANGE_GAP for t in tokens) else None


def find_references(text: str, known: Collection[str] = frozenset()) -> list[Reference]:
    """Clause numbers and ranges named in ``text``, in order of appearance."""
    view, source = normalize(text)
    found: list[Reference] = []
    prev: re.Match[str] | None = None
    prev_is_ref = False
    for match in _NUMBER.finditer(view):
        s, e = match.span()
        number = match.group()
        if len(number) > _MAX_NUMBER:
            prev, prev_is_ref = None, False
            continue
        window = view[max(0, s - _WINDOW) : s]
        words = window.split()
        chunk = words[-1].lstrip(_LEADING) if words else ""
        cut = len(window) == _WINDOW and len(words) == 1  # a word cut by the window
        dotted = "." in number
        direct = (not cut and chunk in _PREFIXES) or (
            dotted and (number in known or chunk in _FROM)
        )
        gap = _gap_tokens(view, prev.end(), s) if prev is not None else None
        is_range = (
            gap is not None and any(t in _RANGE_WORDS for t in gap) and (prev_is_ref or direct)
        )
        if (
            is_range
            and prev is not None
            and not (found and found[-1].high is not None and prev_is_ref)
        ):
            a, _ = span_to_source(source, prev.start(), prev.end())
            _, b = span_to_source(source, s, e)
            if prev_is_ref and found:
                found.pop()
            found.append(Reference(prev.group(), number, a, b))
            prev, prev_is_ref = match, True
            continue
        joined = gap is not None and prev_is_ref and all(t in _JOINERS for t in gap)
        if direct or joined:
            a, b = span_to_source(source, s, e)
            found.append(Reference(number, None, a, b))
            prev, prev_is_ref = match, True
        else:
            prev, prev_is_ref = match, False
    return found


def reference_closure(
    clauses: Sequence[Clause], start_ids: Iterable[str], max_refs: int = 5
) -> dict[str, ClosureEntry]:
    """Per start clause: distinct clauses referenced by number (depth 1), at most ``max_refs``."""
    by_number: dict[str, list[str]] = {}
    by_id: dict[str, Clause] = {}
    keyed: list[tuple[tuple[int, ...], str]] = []
    for clause in clauses:
        by_id.setdefault(clause.id, clause)
        if clause.number is not None:
            by_number.setdefault(clause.number, []).append(clause.id)
            key = number_key(clause.number)
            if key is not None:
                keyed.append((key, clause.id))
    keyed.sort()
    keys = [k for k, _ in keyed]
    result: dict[str, ClosureEntry] = {}
    for sid in start_ids:
        start = by_id.get(sid)
        if start is None or sid in result:
            continue
        seen: dict[str, None] = {}
        for ref in find_references(start.text, by_number.keys()):
            if ref.high is None:
                targets: Iterable[str] = by_number.get(ref.low, ())
            else:
                low, high = number_key(ref.low), number_key(ref.high)
                if low is None or high is None:
                    continue
                lo, hi = bisect_left(keys, low), bisect_right(keys, high)
                targets = [cid for _, cid in keyed[lo:hi]]
            for target in targets:
                if target != sid:
                    seen.setdefault(target, None)
        ordered = tuple(seen)
        result[sid] = ClosureEntry(ordered[:max_refs], len(ordered), len(ordered) > max_refs)
    return result
