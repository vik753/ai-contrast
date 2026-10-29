"""Canaries the detector does not mask yet (S5b-T4), recorded instead of hidden.

Each entry becomes ``xfail(strict=True)`` with the reason below: when the detector gets
better, the test XPASSes, fails, and the entry must be removed. ``GLOBAL_LEAKS`` leak in
every cell where they are planted; ``CELL_LEAKS`` leak only in the named cell.

``SAFETY_NET`` says what ``POST /api/safety-check`` answers for a document that still
holds the canary (checked per canary, alone, as OCR blocks): ``422`` means the second detector
run refuses the document (fail closed); ``200`` means nothing stops it; ``None`` means the
canary is masked when alone and leaks only next to other names (context dependent).
"""

from __future__ import annotations

ONE_WORD = (
    "residual: preview is the final control (one-word ORG without quotes, legal form or definition)"
)

GLOBAL_LEAKS: dict[str, str] = {
    "uk-org-one-word": ONE_WORD,
    "en-org-one-word": ONE_WORD,
}

CELL_LEAKS: dict[tuple[str, str], dict[str, str]] = {}

SAFETY_NET: dict[str, int | None] = {
    "uk-org-one-word": 200,
    "en-org-one-word": 200,
}


def expected_leaks(path: str, location: str) -> dict[str, str]:
    """Canary id -> reason, for the canaries that leak in this cell."""
    found = dict(GLOBAL_LEAKS)
    found.update(CELL_LEAKS.get((path, location), {}))
    return found
