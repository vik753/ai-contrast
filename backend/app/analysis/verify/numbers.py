# ruff: noqa: RUF001, PLR2004, PLR0911, PLR0912, PLR0915, TRY003, E501
"""Number and unit check (ADR 0019 point 3.3 ``number_mismatch``). Linear scan, lexicon data only.

Forms: digits, decimal comma or point, thousands separated by spaces (or a comma followed by
exactly three digits, or repeated groups), words 0-100 in EN/UK/RU, and "десять (10)" (words
and digits are one number; if they disagree the number is unmatchable).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Final, NamedTuple

from app.analysis.verify.lexicon import LANGS, LEXICON, LexiconError
from app.analysis.verify.text import normalize

__all__ = ["number_values"]

_TOKEN: Final = re.compile(r"(?P<num>\d+(?:[   ]\d{3}(?!\d))*(?:[.,]\d+)*)|(?P<word>[^\W\d_]+)")
_WORD: Final = re.compile(r"[^\W\d_]+")
_MAX_DIGITS: Final = 40
_GAP_CHARS: Final = "  -)"
_MAX_GAP: Final = 6
_QUALIFIER_REACH: Final = 60
_CURRENCY: Final = frozenset({"UAH", "USD", "EUR"})


class _Tok(NamedTuple):
    num: bool
    start: int
    end: int
    text: str


class _Cand(NamedTuple):
    start: int
    end: int
    value: Decimal | None


class _Phrases:
    """Whole-word phrases keyed by their first word; symbols are entries not starting with a letter."""

    def __init__(self, entries: list[str]) -> None:
        self.words: dict[str, list[str]] = {}
        self.symbols: list[str] = []
        self._all: list[str] = []
        for raw in entries:
            entry = normalize(raw)[0]
            m = _WORD.match(entry)
            if m is None:
                self.symbols.append(entry)
            else:
                self.words.setdefault(m.group(), []).append(entry)
            self._all.append(entry)

    def match_at(self, view: str, j: int) -> int | None:
        """End of a phrase starting exactly at ``j``, or ``None``."""
        if j >= len(view):
            return None
        if view[j].isalnum():
            m = _WORD.match(view, j)
            if m is None:
                return None
            for entry in self.words.get(m.group(), ()):
                k = j + len(entry)
                if view.startswith(entry, j) and (
                    not entry[-1].isalnum() or k >= len(view) or not view[k].isalnum()
                ):
                    return k
            return None
        for entry in self.symbols:
            if view.startswith(entry, j):
                return j + len(entry)
        return None

    def ends_at(self, view: str, k: int) -> bool:
        """A phrase that ends right before ``k`` (symbol or whole word)."""
        before = view[max(0, k - 40) : k]
        for entry in self._all:
            if before.endswith(entry):
                cut = len(before) - len(entry)
                if not entry[0].isalnum() or cut == 0 or not before[cut - 1].isalnum():
                    return True
        return False


def _build_phrases(per_lang: dict[str, tuple[str, ...]]) -> _Phrases:
    return _Phrases([e for lang in LANGS for e in per_lang[lang]])


_MARKS: Final = _build_phrases(LEXICON.percent_marks)
_UNITS: Final = {u: _build_phrases(w) for u, w in LEXICON.units.items()}


_READ: Final = frozenset(Decimal(i) for i in (*range(20), *range(20, 100, 10), 100))


def _phrase_table() -> dict[tuple[str, ...], tuple[Decimal, bool]]:
    """Number phrases (value, read). Only 0-100 are read by the code; every other listed
    form (halves, hundreds, thousands) is known but unmatchable (fail closed)."""
    table: dict[tuple[str, ...], tuple[Decimal, bool]] = {}
    for lang in LANGS:
        for value, entries in LEXICON.number_words[lang].items():
            read = value in _READ
            for raw in entries:
                key = tuple(_WORD.findall(normalize(raw)[0]))
                if table.setdefault(key, (value, read)) != (value, read):
                    raise LexiconError("number_words.json: phrase with two values")
    return table


_PHRASES: Final = _phrase_table()
_MAX_PHRASE: Final = max(len(k) for k in _PHRASES)
_FIRST_WORDS: Final = frozenset(k[0] for k in _PHRASES)
_WORDS: Final = {k[0]: int(v) for k, (v, read) in _PHRASES.items() if read and len(k) == 1}
# Number words that are in no list: next to a unit word they make the number unmatchable.
_UNREAD_EXACT: Final = frozenset(
    normalize(w)[0] for w in ("quarter", "billion", "billions", "thousands", "millions")
)


def _parse(raw: str) -> Decimal | None:
    if len(raw) > _MAX_DIGITS:
        return None
    s = re.sub(r"[   ]", "", raw)
    seps = [ch for ch in s if ch in ".,"]
    if not seps:
        return Decimal(s)
    last = max(s.rfind("."), s.rfind(","))
    if len(set(seps)) == 2:
        dec = s[last]
        other = "," if dec == "." else "."
        head = s[:last]
        if dec in head:
            return None
        return Decimal(head.replace(other, "") + "." + s[last + 1 :])
    kind = seps[0]
    groups = s.split(kind)
    if len(groups) > 2:
        if 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
            return Decimal("".join(groups))
        return None
    ip, fp = groups
    if kind == "," and len(fp) == 3 and 1 <= len(ip) <= 3 and ip != "0":
        return Decimal(ip + fp)
    return Decimal(ip + "." + fp)


def _candidates(view: str) -> list[_Cand]:
    toks = [
        _Tok(m.lastgroup == "num", m.start(), m.end(), m.group()) for m in _TOKEN.finditer(view)
    ]
    n = len(toks)
    out: list[_Cand] = []

    def joined(a: _Tok, b: _Tok) -> bool:
        return not b.num and view[a.end : b.start].strip("  -") == ""

    def compound(a: _Tok, b: _Tok) -> bool:
        return not b.num and view[a.end : b.start].replace("and", " ").strip(" \u00a0-") == ""

    i = 0
    last_word_end = -1  # token index right after the last number word read
    while i < n:
        t = toks[i]
        if t.num:
            out.append(_Cand(t.start, t.end, _parse(t.text)))
            i += 1
            continue
        hit: tuple[Decimal, bool] | None = None
        used = 0
        if t.text in _FIRST_WORDS:
            for length in range(min(_MAX_PHRASE, n - i), 0, -1):
                seg = toks[i : i + length]
                if not all(joined(seg[k], seg[k + 1]) for k in range(length - 1)):
                    continue
                hit = _PHRASES.get(tuple(x.text for x in seg))
                if hit is not None:
                    used = length
                    break
        if hit is None:
            if t.text in _UNREAD_EXACT:
                out.append(_Cand(t.start, t.end, None))
            i += 1
            continue
        if not hit[1]:
            out.append(_Cand(t.start, toks[i + used - 1].end, None))
            i += used
            continue
        value = int(hit[0])
        adjacent = i == last_word_end and compound(toks[i - 1], t)
        j = i + used
        end = toks[j - 1].end
        if 20 <= value <= 90 and value % 10 == 0 and j < n and joined(toks[j - 1], toks[j]):
            unit_digit = _WORDS.get(toks[j].text, 0)
            if 1 <= unit_digit <= 9:
                value += unit_digit
                end = toks[j].end
                j += 1
        last_word_end = j
        result: Decimal | None = None if adjacent else Decimal(value)
        if j < n and toks[j].num and view[end : toks[j].start].strip("  ") == "(":
            close = view[toks[j].end : toks[j].end + 8].lstrip()
            if close.startswith(")"):
                digits = _parse(toks[j].text)
                if digits != result:
                    result = None
                end = toks[j].end + 8 - len(close) + 1
                j += 1
        out.append(_Cand(t.start, end, result))
        i = j
    return out


def _after_gap(view: str, j: int) -> int:
    k = j
    while k < len(view) and k - j < _MAX_GAP and view[k] in _GAP_CHARS:
        k += 1
    return k


def _unit_check(unit: str | None) -> Callable[[str, _Cand], bool]:
    if unit is None or unit.startswith("percent"):
        qualifiers = None if unit is None else _qualifiers(unit)

        def percent(view: str, cand: _Cand) -> bool:
            mark_end = _MARKS.match_at(view, _after_gap(view, cand.end))
            if mark_end is None:
                return False
            if qualifiers is None:
                return True
            return any(
                view.find(q, mark_end, mark_end + _QUALIFIER_REACH + len(q)) >= 0
                for q in qualifiers
            )

        return percent
    phrases = _UNITS[unit]

    def plain(view: str, cand: _Cand) -> bool:
        if phrases.match_at(view, _after_gap(view, cand.end)) is not None:
            return True
        if unit in _CURRENCY:
            k = cand.start
            if k > 0 and view[k - 1] == " ":
                k -= 1
            return phrases.ends_at(view, k)
        return False

    return plain


def _qualifiers(unit: str) -> list[str]:
    return [normalize(e)[0] for lang in LANGS for e in LEXICON.units[unit][lang]]


def number_values(text: str, unit: str | None) -> set[Decimal | None]:
    """Distinct numbers of ``unit`` in ``text`` (``None``: a number with disagreeing digits and
    words, or too long to read). ``unit=None`` means a plain percentage. An unknown unit gives
    ``{None}``."""
    if unit is not None and unit not in _UNITS:
        return {None}
    view, _ = normalize(text)
    check = _unit_check(unit)
    return {c.value for c in _candidates(view) if check(view, c)}
