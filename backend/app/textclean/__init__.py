"""Shared Layer 1 input cleaning (ADR 0009; threat model T5, T11).

One cleaner for every text path: the extraction child (text, DOCX, PDF) and the
segmentation child. Order: (0) line breaks (CR LF, CR, VT, FF, NEL, LS, PS) become LF,
(a) symbol-font checkbox glyphs are mapped, (b) every code point of the generated table
is removed (default-ignorable, Cf, Co, Cs, Cn, and Cc except TAB, LF, CR), (c) NFC.
Idempotent. Linear time. Runs inside the sandbox child.

``removed`` has one entry per reason: ``default_ignorable``, ``format_character``,
``private_use``, ``unassigned``, ``surrogate``, ``control_character``, with a count and
a sample of at most 16 distinct code points (``U+XXXX``); the sample is never raw text.
"""

from __future__ import annotations

import unicodedata
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Final

from app.extraction.model import Removed
from app.extraction.normalize import normalize_line_breaks
from app.textclean.ignorable_table import RANGES
from app.textclean.symbols import CHECKBOX_TABLE

__all__ = ["CleanResult", "TextCleaner", "clean_text"]

_SAMPLE_CODE_POINTS: Final = 16
_CATEGORY_REASONS: Final = {
    "Cc": "control_character",
    "Cs": "surrogate",
    "Co": "private_use",
    "Cn": "unassigned",
    "Cf": "format_character",
}
_ORDER: Final = (
    "control_character",
    "surrogate",
    "private_use",
    "unassigned",
    "format_character",
    "default_ignorable",
)
_STARTS: Final = [low for low, _ in RANGES]


def _in_table(code_point: int) -> bool:
    index = bisect_right(_STARTS, code_point) - 1
    return index >= 0 and code_point <= RANGES[index][1]


def _reason(char: str) -> str:
    return _CATEGORY_REASONS.get(unicodedata.category(char), "default_ignorable")


@dataclass(frozen=True, slots=True)
class CleanResult:
    text: str
    removed: list[Removed]


class TextCleaner:
    """Cleans many texts and reports one ``removed`` entry per reason."""

    def __init__(self) -> None:
        self._decided: dict[str, str | None] = {}
        self._counts: dict[str, int] = {}
        self._found: dict[str, set[str]] = {}

    def _reason_of(self, char: str) -> str | None:
        try:
            return self._decided[char]
        except KeyError:
            reason = _reason(char) if _in_table(ord(char)) else None
            self._decided[char] = reason
            return reason

    def clean(self, text: str) -> str:
        text = normalize_line_breaks(text)
        if not text.isascii():
            text = text.translate(CHECKBOX_TABLE)
        counts = Counter(text)
        drop: dict[int, None] = {}
        for char, number in counts.items():
            reason = self._reason_of(char)
            if reason is None:
                continue
            drop[ord(char)] = None
            self._counts[reason] = self._counts.get(reason, 0) + number
            found = self._found.setdefault(reason, set())
            if len(found) < _SAMPLE_CODE_POINTS:
                found.add(char)
        if drop:
            text = text.translate(drop)
        return unicodedata.normalize("NFC", text)

    def removed(self) -> list[Removed]:
        """One entry per reason; ``sample`` lists up to 16 distinct ``U+XXXX`` code points
        (never raw text)."""
        return [
            Removed(
                reason=reason,
                count=self._counts[reason],
                sample=" ".join(f"U+{ord(char):04X}" for char in sorted(self._found[reason])),
            )
            for reason in _ORDER
            if reason in self._counts
        ]


def clean_text(text: str) -> CleanResult:
    cleaner = TextCleaner()
    cleaned = cleaner.clean(text)
    return CleanResult(text=cleaned, removed=cleaner.removed())
