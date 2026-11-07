"""Number and unit check (ADR 0019 point 3.3 ``number_mismatch``). Linear scan, lexicon data only.

Read forms: digits, a decimal comma or point, thousands in space groups ("100 000") or repeated
groups ("1.000.000"), words 0-100 in EN/UK/RU (21-99 as compounds) and "десять (10)" or
"10 (десять)" (words and digits are one number). Fail closed: every other form is unmatchable
(``None``): a single separator with three digits ("2.500", "1,000"), two kinds of separators
that are not thousands plus decimals, "5 100" outside currencies, words and digits that
disagree, number words that are not read ("half", "two hundred"), a scale word or suffix after
the number ("10 million", "5k"), and ranges ("5 to 10", "1 000-100 000").
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Final, NamedTuple

from app.analysis.verify.lexicon import LANGS, LEXICON, LexiconError
from app.analysis.verify.text import normalize

__all__ = ["number_values"]

_NBSP: Final = chr(0xA0)
_NNBSP: Final = chr(0x202F)
_SPACES: Final = f" {_NBSP}{_NNBSP}"
_TOKEN: Final = re.compile(
    rf"(?P<num>\d+(?:[{_SPACES}]\d{{3}}(?!\d))*(?:[.,]\d+)*)|(?P<word>[^\W\d_]+)"
)
_WORD: Final = re.compile(r"[^\W\d_]+")
_SPACE_SPLIT: Final = re.compile(f"[{_SPACES}]")
_MAX_DIGITS: Final = 40
_GAP_CHARS: Final = f" {_NBSP}-)"
_MAX_GAP: Final = 6
_WINDOW_TOKENS: Final = 6  # tokens looked at, numbers included, so a flood costs O(1) per number
_WORDS_AFTER: Final = 3
_WORDS_BEFORE: Final = 2
_OPERATOR_CHARS: Final = frozenset("+*\u00d7")
_MAX_RANGE_GAP: Final = 12
_QUALIFIER_REACH: Final = 60
_LOOKBACK: Final = 40
_PAREN_REACH: Final = 8
_GROUP: Final = 3
_KINDS: Final = 2
_UNIT_MAX: Final = 9
_TENS: Final = frozenset(range(20, 100, 10))
_CURRENCY: Final = frozenset({"UAH", "USD", "EUR"})
_READ: Final = frozenset(Decimal(i) for i in (*range(20), *range(20, 100, 10), 100))


class _Tok(NamedTuple):
    num: bool
    start: int
    end: int
    text: str


class _Cand(NamedTuple):
    start: int
    end: int
    value: Decimal | None
    first: int  # index of its first token
    last: int  # index after its last token


class _Words(NamedTuple):
    value: Decimal | None  # None: listed but not read
    next: int  # token index after the words
    end: int  # view offset after the words


class _Phrases:
    """Whole-word phrases keyed by first word; entries not starting with a letter are symbols."""

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
        if not view[j].isalnum():
            return next((j + len(s) for s in self.symbols if view.startswith(s, j)), None)
        m = _WORD.match(view, j)
        for entry in self.words.get(m.group(), ()) if m else ():
            k = j + len(entry)
            if view.startswith(entry, j) and (
                not entry[-1].isalnum() or k >= len(view) or not view[k].isalnum()
            ):
                return k
        return None

    def ends_at(self, view: str, k: int) -> bool:
        """A phrase that ends right before ``k`` (symbol or whole word)."""
        before = view[max(0, k - _LOOKBACK) : k]
        for entry in self._all:
            if before.endswith(entry):
                cut = len(before) - len(entry)
                if not entry[0].isalnum() or cut == 0 or not before[cut - 1].isalnum():
                    return True
        return False


def _build(per_lang: dict[str, tuple[str, ...]]) -> _Phrases:
    return _Phrases([e for lang in LANGS for e in per_lang[lang]])


_MARKS: Final = _build(LEXICON.percent_marks)
_SCALES: Final = _build(LEXICON.scale_words)
_UNITS: Final = {u: _build(w) for u, w in LEXICON.units.items()}
_ALTERNATIVES: Final = (
    "or",
    "and/or",
    "\u0430\u0431\u043e",
    "\u0447\u0438",
    "\u0438\u043b\u0438",
    "\u043b\u0438\u0431\u043e",
    "..",
    "...",
)
# Between two numbers these make the pair ambiguous: ranges and alternatives.
_RANGE_WORDS: Final = frozenset(
    {
        "-",
        *(normalize(w)[0] for lang in LANGS for w in LEXICON.ref_range_words[lang]),
        *(normalize(w)[0] for w in _ALTERNATIVES),
    }
)
_OPERATORS: Final = frozenset(
    normalize(w)[0] for lang in LANGS for w in LEXICON.operator_words[lang]
)
_ALTERNATIVE_WORDS: Final = frozenset(
    normalize(w)[0]
    for lang in LANGS
    for w in (*LEXICON.alternative_words[lang], *LEXICON.ref_range_words[lang])
)
_SAFE: Final = frozenset(normalize(w)[0] for lang in LANGS for w in LEXICON.safe_after_number[lang])


def _phrase_table() -> dict[tuple[str, ...], tuple[Decimal, bool]]:
    """Number phrases as (value, read). Only 0-100 are read; every other listed form (halves,
    hundreds, thousands) is known but unmatchable."""
    table: dict[tuple[str, ...], tuple[Decimal, bool]] = {}
    for lang in LANGS:
        for value, entries in LEXICON.number_words[lang].items():
            for raw in entries:
                key = tuple(_WORD.findall(normalize(raw)[0]))
                if table.setdefault(key, (value, value in _READ)) != (value, value in _READ):
                    raise LexiconError("number_words.json: phrase with two values")  # noqa: TRY003
    return table


_PHRASES: Final = _phrase_table()
_MAX_PHRASE: Final = max(len(k) for k in _PHRASES)
_FIRST_WORDS: Final = frozenset(k[0] for k in _PHRASES)
_WORDS: Final = {k[0]: int(v) for k, (v, read) in _PHRASES.items() if read and len(k) == 1}
# Number words in no list: next to a unit word they make the number unmatchable.
_UNLISTED: Final = frozenset(normalize(w)[0] for w in ("quarter", "billion", "billions"))


def _mixed(s: str, last: int) -> Decimal | None:
    """Both kinds of separator: thousands groups of three, then a decimal part."""
    other = "," if s[last] == "." else "."
    groups = s[:last].split(other)
    if other in s[last + 1 :] or s[last] in s[:last]:
        return None
    if not (1 <= len(groups[0]) <= _GROUP and all(len(g) == _GROUP for g in groups[1:])):
        return None
    return Decimal("".join(groups) + "." + s[last + 1 :])


def _parse(raw: str, *, currency: bool) -> Decimal | None:
    if len(raw) > _MAX_DIGITS:
        return None
    parts = _SPACE_SPLIT.split(raw)
    if len(parts) == _KINDS and len(parts[0]) == 1 and not currency:
        return None  # "5 100": two numbers or one amount, unreadable outside currencies
    return _separated("".join(parts))


def _separated(s: str) -> Decimal | None:
    seps = [ch for ch in s if ch in ".,"]
    if not seps:
        return Decimal(s)
    if len(set(seps)) == _KINDS:
        return _mixed(s, max(s.rfind("."), s.rfind(",")))
    groups = s.split(seps[0])
    if len(groups) > _KINDS:
        ok = 1 <= len(groups[0]) <= _GROUP and all(len(g) == _GROUP for g in groups[1:])
        return Decimal("".join(groups)) if ok else None
    head, tail = groups
    if len(tail) == _GROUP and head != "0":
        return None  # "2.500", "1,000": decimal or thousands, unreadable
    return Decimal(head + "." + tail)


class _Scan:
    """Candidates (numbers in digits or words) of one view."""

    def __init__(self, view: str, *, currency: bool) -> None:
        self.view = view
        self.currency = currency
        self.toks = [
            _Tok(m.lastgroup == "num", m.start(), m.end(), m.group()) for m in _TOKEN.finditer(view)
        ]

    def joined(self, a: _Tok, b: _Tok) -> bool:
        return not b.num and self.view[a.end : b.start].strip(_SPACES + "-") == ""

    def phrase_at(self, i: int) -> tuple[tuple[Decimal, bool], int] | None:
        toks = self.toks
        if toks[i].num or toks[i].text not in _FIRST_WORDS:
            return None
        for length in range(min(_MAX_PHRASE, len(toks) - i), 0, -1):
            seg = toks[i : i + length]
            if all(self.joined(seg[k], seg[k + 1]) for k in range(length - 1)):
                hit = _PHRASES.get(tuple(x.text for x in seg))
                if hit is not None:
                    return hit, length
        return None

    def words_at(self, i: int) -> _Words | None:
        """Number words at token ``i``: a phrase, or tens plus units ("двадцять п'ять")."""
        found = self.phrase_at(i)
        if found is None:
            return None
        (value, read), used = found
        j = i + used
        end = self.toks[j - 1].end
        if not read:
            return _Words(None, j, end)
        number = int(value)
        if number in _TENS and j < len(self.toks) and self.joined(self.toks[j - 1], self.toks[j]):
            unit = _WORDS.get(self.toks[j].text, 0)
            if 1 <= unit <= _UNIT_MAX:
                return _Words(Decimal(number + unit), j + 1, self.toks[j].end)
        return _Words(value, j, end)

    def paren_close(self, end: int) -> int | None:
        """Offset after a ``)`` that follows ``end``, or ``None``."""
        rest = self.view[end : end + _PAREN_REACH]
        stripped = rest.lstrip()
        return end + len(rest) - len(stripped) + 1 if stripped.startswith(")") else None

    def digits_then_words(self, i: int) -> tuple[_Cand, int] | None:
        """ "10 (десять)": the digits and the words must agree."""
        toks = self.toks
        t = toks[i]
        if i + 1 >= len(toks) or toks[i + 1].num:
            return None
        if self.view[t.end : toks[i + 1].start].strip(_SPACES) != "(":
            return None
        words = self.words_at(i + 1)
        close = self.paren_close(words.end) if words else None
        if words is None or close is None:
            return None
        digits = _parse(t.text, currency=self.currency)
        return _Cand(
            t.start, close, digits if digits == words.value else None, i, words.next
        ), words.next

    def words_then_digits(self, i: int, start: int, words: _Words) -> tuple[_Cand, int]:
        """ "десять (10)": one number written twice."""
        toks = self.toks
        value, j, end = words.value, words.next, words.end
        if j < len(toks) and toks[j].num and self.view[end : toks[j].start].strip(_SPACES) == "(":
            close = self.paren_close(toks[j].end)
            if close is not None:
                digits = _parse(toks[j].text, currency=self.currency)
                return _Cand(start, close, value if digits == value else None, i, j + 1), j + 1
        return _Cand(start, end, value, i, j), j

    def candidates(self) -> list[_Cand]:
        toks = self.toks
        out: list[_Cand] = []
        i = 0
        last_words_end = -1  # token index after the last number words
        while i < len(toks):
            t = toks[i]
            if t.num:
                pair = self.digits_then_words(i)
                if pair is not None:
                    out.append(pair[0])
                    i = pair[1]
                else:
                    out.append(
                        _Cand(t.start, t.end, _parse(t.text, currency=self.currency), i, i + 1)
                    )
                    i += 1
                continue
            words = self.words_at(i)
            if words is None:
                if t.text in _UNLISTED:
                    out.append(_Cand(t.start, t.end, None, i, i + 1))
                i += 1
                continue
            cand, nxt = self.words_then_digits(i, t.start, words)
            if i == last_words_end and self.compound(toks[i - 1], t):
                cand = cand._replace(value=None)  # "two five", "two and fifty"
            out.append(cand)
            last_words_end = words.next
            i = nxt
        return self.mark_windows(self.mark_ranges(out))

    def compound(self, a: _Tok, b: _Tok) -> bool:
        return (
            not b.num and self.view[a.end : b.start].replace("and", " ").strip(_SPACES + "-") == ""
        )

    def mark_ranges(self, cands: list[_Cand]) -> list[_Cand]:
        """ "5 to 10", "1 000-100 000": both ends are unmatchable."""
        out = list(cands)
        for k in range(1, len(out)):
            a, b = out[k - 1], out[k]
            gap = self.view[a.end : b.start]
            tokens = gap.replace("-", " - ").split() if len(gap) <= _MAX_RANGE_GAP else []
            if tokens and all(t in _RANGE_WORDS for t in tokens):
                out[k - 1] = a._replace(value=None)
                out[k] = b._replace(value=None)
        return out

    def hit_after(self, k: int) -> bool:
        """Does the word token ``k`` make a neighbouring number unreadable? A scale word, an
        operator word, a number word, or an alternative or range word that stands right before
        a number."""
        tok = self.toks[k]
        if _SCALES.match_at(self.view, tok.start) is not None or tok.text in _OPERATORS:
            return True
        if self.phrase_at(k) is not None:
            return True
        nxt = self.toks[k + 1] if k + 1 < len(self.toks) else None
        return tok.text in _ALTERNATIVE_WORDS and nxt is not None and self.starts_number(nxt, k + 1)

    def starts_number(self, tok: _Tok, k: int) -> bool:
        return tok.num or self.phrase_at(k) is not None

    def window_hit(self, cand: _Cand) -> bool:
        toks = self.toks
        # operator characters between this number and the next token
        nxt = toks[cand.last] if cand.last < len(toks) else None
        gap = self.view[cand.end : nxt.start if nxt else cand.end + _MAX_RANGE_GAP]
        if any(ch in _OPERATOR_CHARS for ch in gap[:_MAX_RANGE_GAP]):
            return True
        if nxt is not None and nxt.text == "x" and cand.last + 1 < len(toks):
            if toks[cand.last + 1].num:
                return True  # "10 x 1000"
        words = 0
        for k in range(cand.last, min(len(toks), cand.last + _WINDOW_TOKENS)):
            if toks[k].num:
                continue
            if self.hit_after(k):
                return True
            words += 1
            if words == _WORDS_AFTER:
                break
        words = 0
        for k in range(cand.first - 1, max(-1, cand.first - 1 - _WINDOW_TOKENS), -1):
            if toks[k].num:
                continue
            if k == cand.first - 1 and toks[k].text in _ALTERNATIVE_WORDS:
                return True  # "between 10", "до 10": a range or alternative word right before
            if _SCALES.match_at(self.view, toks[k].start) is not None or toks[k].text in _OPERATORS:
                return True
            words += 1
            if words == _WORDS_BEFORE:
                break
        return False

    def mark_windows(self, cands: list[_Cand]) -> list[_Cand]:
        """The window rule: a number with a scale word, operator, other number or alternative
        near it is unmatchable."""
        return [c._replace(value=None) if self.window_hit(c) else c for c in cands]


def _after_gap(view: str, j: int) -> int:
    k = j
    while k < len(view) and k - j < _MAX_GAP and view[k] in _GAP_CHARS:
        k += 1
    return k


def _qualifiers(unit: str) -> list[str]:
    return [normalize(e)[0] for lang in LANGS for e in LEXICON.units[unit][lang]]


# A check returns (matches the unit, a scale word follows the number).
_Check = Callable[[str, _Cand], tuple[bool, bool]]


def _percent_check(unit: str | None) -> _Check:
    qualifiers = None if unit is None else _qualifiers(unit)

    def check(view: str, cand: _Cand) -> tuple[bool, bool]:
        mark_end = _MARKS.match_at(view, _after_gap(view, cand.end))
        if mark_end is None:
            return False, False
        if qualifiers is None:
            return True, False
        return any(
            view.find(q, mark_end, mark_end + _QUALIFIER_REACH + len(q)) >= 0 for q in qualifiers
        ), False

    return check


def _unknown_word(view: str, j: int) -> int | None:
    """End of a letters-only word at ``j`` that is no function word, unit, mark or scale."""
    m = _WORD.match(view, j) if j < len(view) else None
    if m is None or m.group() in _SAFE:
        return None
    if _SCALES.match_at(view, j) is not None or _MARKS.match_at(view, j) is not None:
        return None
    if any(p.match_at(view, j) is not None for p in _UNITS.values()):
        return None
    return m.end()


def _plain_check(unit: str) -> _Check:
    phrases = _UNITS[unit]

    def check(view: str, cand: _Cand) -> tuple[bool, bool]:
        k = cand.start - 1 if cand.start > 0 and view[cand.start - 1] == " " else cand.start
        before = unit in _CURRENCY and phrases.ends_at(view, k)
        gap_end = _after_gap(view, cand.end)
        scale_end = _SCALES.match_at(view, gap_end)
        if scale_end is None:
            scale_end = _unknown_word(view, gap_end)  # may be a scale or unit we do not know
        if scale_end is not None:
            after = phrases.match_at(view, _after_gap(view, scale_end)) is not None
            return after or before, True
        return phrases.match_at(view, gap_end) is not None or before, False

    return check


def number_values(text: str, unit: str | None) -> set[Decimal | None]:
    """Distinct numbers of ``unit`` in ``text``; ``None`` stands for a number that cannot be
    read (see the module note). ``unit=None`` means a plain percentage. An unknown unit gives
    ``{None}``."""
    if unit is not None and unit not in _UNITS:
        return {None}
    view, _ = normalize(text)
    percent = unit is None or unit.startswith("percent")
    check = _percent_check(unit) if percent else _plain_check(unit or "")
    found: set[Decimal | None] = set()
    for cand in _Scan(view, currency=unit in _CURRENCY).candidates():
        matched, scaled = check(view, cand)
        if matched:
            found.add(None if scaled else cand.value)
    return found
