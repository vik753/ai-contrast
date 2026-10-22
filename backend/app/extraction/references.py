# ruff: noqa: RUF001, RUF002, RUF003 - Ukrainian and Russian legal phrases are the point of this module
"""References to documents that were not provided (S3-T3 AC12; ADR 0009 Layer 0).

Shared post-processing for every kind (text, DOCX, PDF); runs inside the parsing
child. A contract that applies other rules or annexes ("згідно з Правилами
страхування", "General Terms and Conditions", "є невід'ємною частиною") may hold
terms the comparison never sees. The warning ``external_reference`` tells the
person to provide them.

Matching: casefolded text, whitespace runs as one space, typographic apostrophes
(’ ʼ ` ′) as ``'``. One warning per document (``page`` null) for text and DOCX,
one per page with a match for PDF, in page order. The text is never changed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from app.extraction.model import Block, Warning

EXTERNAL_REFERENCE: Final = "external_reference"

_APOSTROPHES: Final = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "′": "'", "‘": "'"})
_PATTERNS: Final = re.compile(
    "|".join(
        [
            # Ukrainian: "згідно з/із Правилами", "відповідно до Правил", "невід'ємна частина".
            r"згідно\s+(?:з|із|зі)\s+правил",
            r"відповідно\s+до\s+правил",
            r"невід'?ємн\w*\s+частин",
            # Russian: "согласно Правилам", "в соответствии с Правилами", "неотъемлемая часть".
            r"согласно\s+правил",
            r"в\s+соответствии\s+с\s+правил",
            r"неотъемлем\w*\s+част",
            # English.
            r"general\s+terms\s+and\s+conditions",
            r"general\s+conditions\s+of",
            r"incorporated\s+(?:herein\s+)?by\s+reference",
            r"(?:forms?|constitutes?|is)\s+an?\s+integral\s+part",
        ]
    )
)
_SPACE: Final = re.compile(r"\s+")


def mentions_external_document(text: str) -> bool:
    key = _SPACE.sub(" ", text.translate(_APOSTROPHES).casefold())
    return _PATTERNS.search(key) is not None


def external_reference_warnings(blocks: Sequence[Block], *, per_page: bool) -> list[Warning]:
    """``external_reference`` warnings for ``blocks`` (see the module doc)."""
    if not per_page:
        found = any(mentions_external_document(block.text) for block in blocks)
        return [Warning(code=EXTERNAL_REFERENCE, page=None)] if found else []
    pages = sorted(
        {
            block.page
            for block in blocks
            if block.page is not None and mentions_external_document(block.text)
        }
    )
    return [Warning(code=EXTERNAL_REFERENCE, page=page) for page in pages]
