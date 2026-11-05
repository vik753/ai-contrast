"""The clauses of a checked document as ``TagClause`` values."""

from __future__ import annotations

from app.pseudo.gate import PseudonymizedDocument
from app.tagging.model import TagClause

__all__ = ["clauses_of"]


def clauses_of(document: PseudonymizedDocument) -> list[TagClause]:
    """One ``TagClause`` per clause, in order. Clause headings are not part of the masked
    document, so ``heading`` stays empty."""
    return [TagClause(clause.id, clause.text) for clause in document.clauses]
