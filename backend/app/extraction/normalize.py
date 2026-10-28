# ruff: noqa: RUF001 - page-number words (UK, RU) and dashes are the point of the pattern
"""Text normalization shared by every extractor (S3-T1 AC4, S3-T2 AC8; threat model T4).

Runs inside the parsing child (ADR 0011).

- Line breaks become ``\\n``: CR LF, CR, NEL (U+0085), LS (U+2028), PS (U+2029),
  and also FF and VT, so that words on both sides never run together.
- Invisible and control characters are removed by ``app.textclean`` (ADR 0009 Layer 1).
"""

from __future__ import annotations

import re
from typing import Final

_LINE_BREAKS: Final = re.compile(r"\r\n|[\r\x0b\x0c\u0085\u2028\u2029]")
# A header or footer line that holds only a page number ("7", "- 3 -", "Page 2 of 5").
PAGE_NUMBER_LINE: Final = re.compile(
    r"[\s\-–—]*(?:(?:page|p\.|pg\.?|сторінка|стор\.?|страница|стр\.?)\s*)?\d{1,5}"
    r"(?:\s*(?:of|/|з|із|из)\s*\d{1,5})?[\s\-–—]*",
    re.IGNORECASE,
)


def normalize_line_breaks(text: str) -> str:
    """CR LF, CR, VT, FF, NEL, LS and PS become LF (control characters are removed later
    by ``app.textclean``)."""
    return _LINE_BREAKS.sub("\n", text)
