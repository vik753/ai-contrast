"""Keyword tags (ADR 0018 point 2): synonyms of confirmed topics on the skeleton view.

Heading and text are scanned separately and never joined into one phrase. Linear time.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.pseudo.gate import ConfirmedTopic
from app.tagging.model import TagClause
from app.tagging.phrases import PhraseIndex, folded_view

__all__ = ["KEYWORD_RULES_VERSION", "keyword_tags"]

# Bump when the matching rules change (read at call time by ``tagging_version``).
KEYWORD_RULES_VERSION: Final = "kw-1"


def keyword_tags(
    clauses: Sequence[TagClause], topics: Sequence[ConfirmedTopic]
) -> dict[str, set[str]]:
    """Topic ids per clause id; every clause id is a key (empty set: no tag)."""
    index = PhraseIndex(
        (topic.topic_id, synonym)
        for topic in topics
        for synonym in (*topic.synonyms_en, *topic.synonyms_uk, *topic.synonyms_ru)
    )
    result: dict[str, set[str]] = {}
    for clause in clauses:
        found = result.setdefault(clause.id, set())
        for part in (clause.heading, clause.text):
            if part:
                view, _ = folded_view(part)
                found.update(key for key, _, _ in index.find(view))
    return result
