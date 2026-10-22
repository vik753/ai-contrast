"""Text normalization shared by every extractor (S3-T1 AC4, S3-T2 AC8; threat model T4).

Runs inside the parsing child (ADR 0011).

- Line breaks become ``\\n``: CR LF, CR, NEL (U+0085), LS (U+2028), PS (U+2029),
  and also FF and VT, so that words on both sides never run together.
- Other control characters (Unicode category Cc; TAB and LF are kept) are removed
  and reported in ``removed`` with the reason ``control_characters`` and a sample of
  their code points such as ``U+0001``.

``ControlCleaner`` keeps the count and the sample across many calls, so that one
document gives one ``removed`` entry.
"""

from __future__ import annotations

import re
from typing import Final

from app.extraction.model import Removed

CONTROL_CHARACTERS: Final = "control_characters"

# Cc characters that are kept: TAB and LF. The line breaks below become LF first.
_LINE_BREAKS: Final = re.compile(r"\r\n|[\r\x0b\x0c\u0085\u2028\u2029]")
_REMOVED_CONTROLS: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# How many distinct code points the sample lists (each ``U+XXXX`` is 6 characters).
_SAMPLE_CODE_POINTS: Final = 16


class ControlCleaner:
    """Normalizes line breaks and removes control characters, counting them."""

    def __init__(self) -> None:
        self._count = 0
        self._found: set[str] = set()

    def _note(self, match: re.Match[str]) -> str:
        self._count += 1
        if len(self._found) < _SAMPLE_CODE_POINTS:
            self._found.add(match.group())
        return ""

    def clean(self, text: str) -> str:
        return _REMOVED_CONTROLS.sub(self._note, _LINE_BREAKS.sub("\n", text))

    def removed(self) -> list[Removed]:
        if not self._count:
            return []
        sample = " ".join(f"U+{ord(char):04X}" for char in sorted(self._found))
        return [Removed(reason=CONTROL_CHARACTERS, count=self._count, sample=sample)]
