# ruff: noqa: RUF001, RUF002, RUF003 - Ukrainian and Russian legal phrases are the point of this module
"""References to documents that were not provided (S3-T3 AC12; ADR 0009 Layer 0).

Shared post-processing for every kind (text, DOCX, PDF); runs inside the parsing
child. A contract that applies other rules or annexes ("згідно з Правилами
страхування", "General Terms and Conditions", "є невід'ємною частиною") may hold
terms the comparison never sees. The warning ``external_reference`` tells the
person to provide them.

Matching: casefolded text, whitespace runs as one space, typographic apostrophes
(’ ʼ ` ′) as ``'``. A phrase may be split between two adjacent blocks (a paragraph
break, a page break): the end of a block and the start of the next one are joined
and searched too (``JOIN_CHARS`` on each side, more than the longest phrase). One
warning per document (``page`` null) for text and DOCX, one per page with a match
for PDF, in page order; a phrase split over a page break is reported on the page
where it starts. The text is never changed.
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
JOIN_CHARS: Final = 120


def _key(text: str) -> str:
    return _SPACE.sub(" ", text.translate(_APOSTROPHES).casefold())


def mentions_external_document(text: str) -> bool:
    return _PATTERNS.search(_key(text)) is not None


def straddles(tail: str, head: str) -> bool:
    """A phrase starts in ``tail`` and ends in ``head`` (two adjacent blocks)."""
    left = _key(tail)
    joined = f"{left} {_key(head)}"
    return any(m.start() < len(left) < m.end() for m in _PATTERNS.finditer(joined))


def _hits(blocks: Sequence[Block]) -> list[Block]:
    """Blocks in which a reference starts (inside the block or across its end)."""
    found = []
    for index, block in enumerate(blocks):
        following = blocks[index + 1].text[:JOIN_CHARS] if index + 1 < len(blocks) else None
        if mentions_external_document(block.text) or (
            following is not None and straddles(block.text[-JOIN_CHARS:], following)
        ):
            found.append(block)
    return found


def external_reference_warnings(blocks: Sequence[Block], *, per_page: bool) -> list[Warning]:
    """``external_reference`` warnings for ``blocks`` (see the module doc)."""
    hits = _hits(blocks)
    if not per_page:
        return [Warning(code=EXTERNAL_REFERENCE, page=None)] if hits else []
    pages = sorted({block.page for block in hits if block.page is not None})
    return [Warning(code=EXTERNAL_REFERENCE, page=page) for page in pages]
