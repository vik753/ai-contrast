"""Shared types of the tagging package (ADR 0018)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["TagClause", "TagMergeError", "ensure_unique_ids"]


@dataclass(frozen=True, slots=True)
class TagClause:
    """One clause. The heading counts as clause text."""

    id: str
    text: str
    heading: str | None = None


class TagMergeError(Exception):
    """A refused merge. ``str(error)`` is the code only (never client data)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def ensure_unique_ids(clauses: Sequence[TagClause]) -> None:
    """Refuse two clauses with the same id (a repeated id could hide a clause)."""
    if len({c.id for c in clauses}) != len(clauses):
        raise TagMergeError("duplicate_clause_id")
