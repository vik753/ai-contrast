"""Partial values next to a placeholder (ADR 0015 point 4, review of S5b-T2).

The browser masks whole values. A letter or digit run that touches a placeholder, or that is
reached from it over separators only, is the rest of a value that was masked in part (an
IBAN tail, the head of a phone number, an e-mail local part). For a code class (``TAX_ID``,
``ACCOUNT``, ``PHONE``, ``PERSONAL_DOC``, ``DOC_NO``, ``VEHICLE``) a space is a separator
too, but only code-like runs count (a digit in the run; for ``VEHICLE`` also two
capital letters), so plain words after a code stay allowed. For other classes only a run
without white space in between counts. Each side follows at most ``MAX_RUNS`` runs. The scan
returns offsets only and is linear in the text.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Final

from app.pseudo.matching import DASH_CODES
from app.safety.placeholders import Placeholder

CODE_CLASSES: Final = frozenset({"TAX_ID", "ACCOUNT", "PHONE", "PERSONAL_DOC", "DOC_NO", "VEHICLE"})
MAX_RUNS: Final = 8
_ASCII_SEPARATORS: Final = frozenset("-.@/+()")
_OTHER_SEPARATORS: Final = _ASCII_SEPARATORS | frozenset(map(chr, DASH_CODES))
_CODE_CATEGORIES: Final = frozenset({"Pd", "Pc", "Po", "Sm"})
_PLATE_LETTERS: Final = 2


def is_separator(char: str, code: bool) -> bool:
    """A separator after a placeholder. Code classes: any white space except a line break,
    dash, connector, other punctuation or math symbol (``|``), and ``+()/@``. Other classes:
    ASCII separators and every Unicode dash, never white space."""
    if not code:
        return char in _OTHER_SEPARATORS
    if char.isspace():
        return char != "\n"
    return char in _ASCII_SEPARATORS or unicodedata.category(char) in _CODE_CATEGORIES


def _code_like(run: str, cls: str) -> bool:
    if any(char.isdigit() for char in run):
        return True
    return cls == "VEHICLE" and run.isalpha() and run.isupper() and len(run) == _PLATE_LETTERS


def _right(text: str, end: int, cls: str, out: list[tuple[int, int]]) -> None:
    space = cls in CODE_CLASSES
    position, size = end, len(text)
    for step in range(MAX_RUNS):
        start = position
        while start < size and is_separator(text[start], space):
            start += 1
        if start >= size or not text[start].isalnum():
            return
        stop = start
        while stop < size and text[stop].isalnum():
            stop += 1
        if space and not (step == 0 and start == end) and not _code_like(text[start:stop], cls):
            return
        out.append((start, stop))
        position = stop


def _left(text: str, begin: int, cls: str, out: list[tuple[int, int]]) -> None:
    space = cls in CODE_CLASSES
    position = begin
    for step in range(MAX_RUNS):
        stop = position
        while stop > 0 and is_separator(text[stop - 1], space):
            stop -= 1
        if stop <= 0 or not text[stop - 1].isalnum():
            return
        start = stop
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        if space and not (step == 0 and stop == begin) and not _code_like(text[start:stop], cls):
            return
        out.append((start, stop))
        position = start


def partial_spans(
    texts: Sequence[str], placeholders: Sequence[Sequence[Placeholder]]
) -> set[tuple[int, int, int]]:
    """Leftover runs next to placeholders as ``(clause_index, start, end)``."""
    result: set[tuple[int, int, int]] = set()
    for index, (text, found) in enumerate(zip(texts, placeholders, strict=True)):
        runs: list[tuple[int, int]] = []
        for start, end, cls in found:
            _left(text, start, cls, runs)
            _right(text, end, cls, runs)
        result.update((index, start, end) for start, end in runs)
    return result
