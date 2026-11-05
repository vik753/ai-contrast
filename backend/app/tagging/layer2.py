"""Layer 2 per clause (ADR 0018 point 6): hits only; a clause with a hit stays in the flow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.injection import Hit, scan
from app.tagging.model import TagClause

__all__ = ["ClauseHits", "clause_hits"]


@dataclass(frozen=True, slots=True)
class ClauseHits:
    """Hits in the clause text and in its heading (offsets relative to each string)."""

    text: list[Hit]
    heading: list[Hit]


def clause_hits(clauses: Sequence[TagClause]) -> dict[str, ClauseHits]:
    """Only clauses with at least one hit."""
    result: dict[str, ClauseHits] = {}
    for clause in clauses:
        text = scan(clause.text)
        heading = scan(clause.heading) if clause.heading else []
        if text or heading:
            result[clause.id] = ClauseHits(text=text, heading=heading)
    return result
