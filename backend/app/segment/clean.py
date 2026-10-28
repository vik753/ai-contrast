"""Input cleaning of the segmentation child (ADR 0009 layer 1, ADR 0014 point 2).

The same ``ControlCleaner`` as extraction (line breaks, control characters), plus the
format characters that a reader does not see: category ``Cf`` (zero-width space and
joiners, bidi marks, byte order mark, soft hyphen), the other default-ignorable code
points (variation selectors, fillers, combining grapheme joiner) and lone surrogates.
OCR text and the browser's copy are never trusted to be clean.

``removed`` reports each reason once with a count and a sample of code points.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from app.extraction.model import Removed
from app.extraction.normalize import ControlCleaner

FORMAT_CHARACTERS: Final = "format_characters"
_SAMPLE_CODE_POINTS: Final = 16
# Default-ignorable code points that are not in category Cf.
_EXTRA_IGNORABLE: Final = frozenset(
    {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0}
    | set(range(0x180B, 0x1810))
    | set(range(0xFE00, 0xFE10))
    | set(range(0xE0100, 0xE01F0))
)


def _is_removed(char: str) -> bool:
    return unicodedata.category(char) in ("Cf", "Cs") or ord(char) in _EXTRA_IGNORABLE


class InputCleaner:
    """Cleans many texts and reports one ``removed`` entry per reason."""

    def __init__(self) -> None:
        self._controls = ControlCleaner()
        self._decided: dict[str, bool] = {}
        self._table: dict[int, None] = {}
        self._count = 0
        self._found: set[str] = set()

    def clean(self, text: str) -> str:
        text = self._controls.clean(text)
        if text.isascii():
            return text
        distinct = set(text)
        for char in distinct:
            if char not in self._decided:
                removed = _is_removed(char)
                self._decided[char] = removed
                if removed:
                    self._table[ord(char)] = None
        hits = [char for char in distinct if self._decided[char]]
        if not hits:
            return text
        cleaned = text.translate(self._table)
        self._count += len(text) - len(cleaned)
        for char in hits:
            if len(self._found) < _SAMPLE_CODE_POINTS:
                self._found.add(char)
        return cleaned

    def removed(self) -> list[Removed]:
        entries = self._controls.removed()
        if self._count:
            sample = " ".join(f"U+{ord(char):04X}" for char in sorted(self._found))
            entries.append(Removed(reason=FORMAT_CHARACTERS, count=self._count, sample=sample))
        return entries
