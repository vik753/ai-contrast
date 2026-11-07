# ruff: noqa: RUF001, RUF002
"""One normalization for lexicon entries and text, and phrase finders over lexicon data.

The view is NFKC, upper-then-skeleton-then-lower (Latin/Cyrillic look-alikes share one
form), ``ё`` as ``е``, hyphen and dash variants as ``-``, the apostrophe variants as one
character (an in-word apostrophe is a letter, as in ``app.tagging.phrases``), and the
default-ignorable and format characters removed (``app.textclean`` table). Offsets map back
to the original text. Linear time; no regex is built from text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

from app.pseudo.matching import DASH_FOLD, fold_view
from app.tagging.phrases import PhraseIndex
from app.textclean.ignorable_table import RANGES

__all__ = ["Markers", "Source", "normalize", "span_to_source"]

Source = tuple[list[int], list[int]]  # view index -> source start / source end

_WORD: Final = re.compile(r"[^\W_]+")
_IGNORABLE: Final = re.compile(
    "[" + "".join(f"\\U{low:08x}-\\U{high:08x}" for low, high in RANGES) + "]"
)
# A non-ASCII decimal digit (category Nd) that NFKC leaves: the skeleton may turn it into a
# letter or a dot, so it becomes a caret and any number it touches is unreadable.
_FOREIGN_DIGIT: Final = re.compile(r"[^\x00-\x7f\D]")
_IN_WORD_APOSTROPHE: Final = re.compile(r"(?<=\w)'(?=\w)")
_JOINER: Final = "ʼ"  # a letter: an apostrophe between letters stays inside the word
# Superscripts, subscripts and vulgar fractions: NFKC would turn "10²" into "102". A caret
# keeps the number from being read (a symbol touches it).
_PRE: Final = {
    **{ord(c): ord("^") for c in "\u00b2\u00b3\u00b9\u2070\u2074\u2075\u2076\u2077\u2078\u2079"},
    **{code: ord("^") for code in range(0x2080, 0x208A)},
    **{ord(c): ord("^") for c in "\u00bc\u00bd\u00be"},
    **{code: ord("^") for code in range(0x2150, 0x215F)},
}
_TRANSLATE: Final = {
    **DASH_FOLD,
    0x2018: ord("'"),
    0x2019: ord("'"),
    0x02BC: ord("'"),
    0x0060: ord("'"),
}


# Order of steps. The lexicon README lists NFKC, case folding, yo as ye, apostrophes, dashes, the
# UTS #39 skeleton, whitespace. Here the apostrophe and dash maps run right after NFKC and
# before the skeleton, and ``fold_view`` is upper case, skeleton, lower case, with the capital
# yo mapped like the capital ye. The result is the same: the maps touch only punctuation, the
# skeleton leaves punctuation of those kinds alone, and a skeleton applied to ye gives the
# same letter as to yo. Whitespace runs are one flexible separator in ``PhraseIndex``.
def _tidy(view: str) -> str:
    view = view.replace("ё", "е")
    if "'" in view:
        view = _IN_WORD_APOSTROPHE.sub(_JOINER, view)
    return view


def normalize(text: str) -> tuple[str, Source | None]:
    """The matching view and, when its length differs from ``text``, the map back."""
    if (
        _IGNORABLE.search(text) is None
        and _FOREIGN_DIGIT.search(text) is None
        and unicodedata.is_normalized("NFKC", text)
    ):
        return _tidy(fold_view(text.translate(_TRANSLATE))), None
    return _normalize_slow(text)


def _normalize_slow(text: str) -> tuple[str, Source | None]:
    n = len(text)
    cache: dict[str, str] = {}
    pieces: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    changed = False
    i = 0
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        chunk = text[i:j]
        piece = cache.get(chunk)
        if piece is None:
            kept = _IGNORABLE.sub("", chunk).translate(_PRE)
            piece = fold_view(
                _FOREIGN_DIGIT.sub("^", unicodedata.normalize("NFKC", kept)).translate(_TRANSLATE)
            )
            cache[chunk] = piece
        pieces.append(piece)
        if len(piece) != j - i:
            changed = True
        starts.extend([i] * len(piece))
        ends.extend([j] * len(piece))
        i = j
    view = _tidy("".join(pieces))
    return view, ((starts, ends) if changed else None)


def span_to_source(source: Source | None, a: int, b: int) -> tuple[int, int]:
    """Map a view span to source offsets, snapped outward to whole source characters."""
    if source is None or b <= a:
        return a, b
    return source[0][a], source[1][b - 1]


class Markers:
    """Literal phrases of the lexicons. English words match whole words, Ukrainian and
    Russian entries also match longer forms (stems). A hyphen counts as a space."""

    def __init__(self, entries: Iterable[tuple[str, str]]) -> None:
        self._index = PhraseIndex(
            (("m", _entry(lang, phrase)) for lang, phrase in entries), exact_marker=True
        )

    def find(self, text: str) -> list[tuple[int, int]]:
        """Every match as source offsets into ``text``, in view order."""
        if not text:
            return []
        view, source = normalize(text)
        return self.find_in(view, source)

    def find_in(self, view: str, source: Source | None) -> list[tuple[int, int]]:
        """``find`` on a text that ``normalize`` already processed."""
        return [
            span_to_source(source, a, b) for _, a, b in self._index.find(view.replace("-", " "))
        ]

    def first_in(self, view: str, source: Source | None) -> tuple[int, int] | None:
        found = self.find_in(view, source)
        return found[0] if found else None


def _entry(lang: str, phrase: str) -> str:
    view = normalize(phrase)[0].replace("-", " ")
    if lang == "en":
        return _WORD.sub(lambda m: m.group() + "$", view)
    return view
