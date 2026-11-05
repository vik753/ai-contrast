"""Shared types of the tagging package (ADR 0018)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TagClause", "TagMergeError"]


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
