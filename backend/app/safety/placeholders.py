"""Placeholder grammar of masked text (ADR 0015 point 4).

This module is outside ``app/pseudo`` because that package forbids whole-text regex calls;
here every candidate is bounded to 40 characters, so the scan is linear.

A placeholder is ``[<label>.<CLASS>_<n>]``: ``label`` is the document label, ``CLASS`` a
known entity class, ``n`` from 1 to 5000 without a leading zero. Candidates are found on
the confusable skeleton, so a look-alike written with Cyrillic or Greek letters or other
digits is a candidate that fails the literal check. Only the literal ``[`` and ``]`` count
(a neutralized ``⟦…⟧`` is ordinary text). Numbering is per class, from 1, without gaps,
over the whole document. Nothing here returns or logs text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, get_args

from app.pseudo.matching import SKELETON
from app.segment.model import EntityClass

CLASSES: Final = frozenset(get_args(EntityClass))
MAX_NUMBER: Final = 5000
_CANDIDATE: Final = re.compile(r"\[([^\[\]\s]{1,40})\]")
_LETTER_DOT: Final = re.compile(r"[^\W\d_]\.")
_STRICT: Final = re.compile(r"\[([A-Z])\.([A-Z_]+)_([1-9][0-9]{0,3})\]", re.ASCII)

Range = tuple[int, int]


class PlaceholderError(Exception):
    """A placeholder-like token is invalid. The message holds no input."""

    def __init__(self) -> None:
        super().__init__("invalid_placeholder")


def find_placeholders(label: str, texts: Sequence[str]) -> list[list[Range]]:
    """Valid placeholder ranges per text. Raises ``PlaceholderError`` on a bad one or a gap."""
    ranges: list[list[Range]] = []
    numbers: dict[str, set[int]] = {}
    for text in texts:
        found: list[Range] = []
        skeleton = text.translate(SKELETON)
        for candidate in _CANDIDATE.finditer(skeleton):
            content = candidate.group(1)
            if "_" not in content and _LETTER_DOT.match(content) is None:
                continue
            start, end = candidate.span()
            matched = _STRICT.fullmatch(text, start, end)
            if matched is None or matched.group(1) != label:
                raise PlaceholderError
            cls, number = matched.group(2), int(matched.group(3))
            if cls not in CLASSES or number > MAX_NUMBER:
                raise PlaceholderError
            numbers.setdefault(cls, set()).add(number)
            found.append((start, end))
        ranges.append(found)
    if any(seen != set(range(1, len(seen) + 1)) for seen in numbers.values()):
        raise PlaceholderError
    return ranges
