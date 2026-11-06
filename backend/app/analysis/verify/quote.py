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
_CLOSERS: Final = frozenset(")]\"'»\u201d\u2019\u203a")
_MAX_CLOSERS: Final = 3
_NUMBER_DOTS: Final = 2


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
    """Every occurrence of the quote in ``clause.text`` (overlapping too), as offsets."""
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
        i = folded.find(needle, i + 1)  # overlapping occurrences count too
    return QuoteCheck(bool(spans), tuple(spans))


class _Abbreviations:
    __slots__ = ("may", "never")

    def __init__(self, never: frozenset[str], may: frozenset[str]) -> None:
        self.never = never
        self.may = may


_DEFAULT: Final = _Abbreviations(LEXICON.never_end, LEXICON.may_end)


def _sentence_end(text: str, i: int, ab: _Abbreviations) -> int | None:
    """Offset after the sentence end at ``text[i]``, or ``None`` when it is not one.

    The terminator may be followed by up to three closing quotes or brackets (``."``, ``.)``);
    they belong to the sentence. Then whitespace or the end of the text must follow."""
    n = len(text)
    k = i + 1
    while k < n and k - i <= _MAX_CLOSERS and text[k] in _CLOSERS:
        k += 1
    if k < n and not text[k].isspace():
        return None
    if text[i] != "." or not _abbreviation_blocks(text, i, k, ab):
        return k
    return None


def _abbreviation_blocks(text: str, i: int, k: int, ab: _Abbreviations) -> bool:
    """Is the period at ``text[i]`` part of an abbreviation or a clause number?"""
    t = i
    while t > 0 and i - t < _TOKEN_MAX and not text[t - 1].isspace() and text[t - 1] != "(":
        t -= 1
    if i - t >= _TOKEN_MAX:
        return False
    token = text[t : i + 1].lower()
    if token.count(".") >= _NUMBER_DOTS and token.replace(".", "").isdigit():
        return True  # a clause number such as "4.2."
    if token in ab.never:
        return True
    if token in ab.may:
        n = len(text)
        j = k
        while j < n and text[j].isspace():
            j += 1
        return not (j >= n or text[j].isupper() or text[j].isdigit())
    return False


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
    s = 0
    for i in range(start - 1, -1, -1):
        if text[i] in _TERMS:
            found = _sentence_end(text, i, ab)
            if found is not None:
                s = min(found, start)
                break
    while s < start and text[s].isspace():
        s += 1
    e = n
    for j in range(max(end - 1, start), n):
        if text[j] in _TERMS:
            found = _sentence_end(text, j, ab)
            if found is not None:
                e = found
                break
    return s, e
