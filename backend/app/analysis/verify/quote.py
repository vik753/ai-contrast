# ruff: noqa: PLR2004, PLR0911
"""Quote check (whitespace folding only) and expansion to the sentence (ADR 0019 point 3.1-3.2)."""

from __future__ import annotations

import re
from typing import Final

from app.analysis.verify.lexicon import LEXICON
from app.analysis.verify.model import Clause, QuoteCheck

__all__ = ["expand_quote", "verify_quote"]

_WS: Final = re.compile(r"\s+")
_ODD_WS: Final = re.compile(r"[^\S ]| {2}")
_TERMS: Final = frozenset(".;!?")
_TOKEN_MAX: Final = 16


def _fold(text: str) -> tuple[str, list[int] | None, list[int] | None]:
    """Whitespace runs as one space, with the original start and end of every character."""
    if _ODD_WS.search(text) is None:
        return text, None, None
    parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pos = 0
    for match in _WS.finditer(text):
        s, e = match.span()
        if s > pos:
            parts.append(text[pos:s])
            starts.extend(range(pos, s))
            ends.extend(range(pos + 1, s + 1))
        parts.append(" ")
        starts.append(s)
        ends.append(e)
        pos = e
    if pos < len(text):
        parts.append(text[pos:])
        starts.extend(range(pos, len(text)))
        ends.extend(range(pos + 1, len(text) + 1))
    return "".join(parts), starts, ends


def verify_quote(clause: Clause, quote: str) -> QuoteCheck:
    """Every occurrence of the quote in ``clause.text`` (non-overlapping), as offsets."""
    needle = _WS.sub(" ", quote).strip(" ")
    if not needle:
        return QuoteCheck(False, ())
    folded, starts, ends = _fold(clause.text)
    spans: list[tuple[int, int]] = []
    i = folded.find(needle)
    while i >= 0:
        j = i + len(needle)
        if starts is None or ends is None:
            spans.append((i, j))
        else:
            spans.append((starts[i], ends[j - 1]))
        i = folded.find(needle, j)
    return QuoteCheck(bool(spans), tuple(spans))


class _Abbreviations:
    __slots__ = ("may", "never")

    def __init__(self, never: frozenset[str], may: frozenset[str]) -> None:
        self.never = never
        self.may = may


_DEFAULT: Final = _Abbreviations(LEXICON.never_end, LEXICON.may_end)


def _is_end(text: str, i: int, ab: _Abbreviations) -> bool:
    n = len(text)
    if i + 1 < n and not text[i + 1].isspace():
        return False
    if text[i] != ".":
        return True
    k = i
    while k > 0 and i - k < _TOKEN_MAX and not text[k - 1].isspace() and text[k - 1] != "(":
        k -= 1
    if i - k >= _TOKEN_MAX:
        return True
    token = text[k : i + 1].lower()
    if token.count(".") >= 2 and token.replace(".", "").isdigit():
        return False  # a clause number such as "4.2."
    if token in ab.never:
        return False
    if token in ab.may:
        j = i + 1
        while j < n and text[j].isspace():
            j += 1
        return j >= n or text[j].isupper() or text[j].isdigit()
    return True


def expand_quote(
    text: str, start: int, end: int, abbreviations: frozenset[str] | None = None
) -> tuple[int, int]:
    """The sentence (or sentences) around ``[start, end)``, inside ``[0, len(text)]``."""
    n = len(text)
    start = min(max(start, 0), n)
    end = min(max(end, start), n)
    ab = (
        _DEFAULT
        if abbreviations is None
        else _Abbreviations(frozenset(a.lower() for a in abbreviations), frozenset())
    )
    i = start - 1
    while i >= 0 and not (text[i] in _TERMS and _is_end(text, i, ab)):
        i -= 1
    s = i + 1
    while s < start and text[s].isspace():
        s += 1
    j = max(end - 1, start)
    while j < n and not (text[j] in _TERMS and _is_end(text, j, ab)):
        j += 1
    return s, min(j + 1, n)
