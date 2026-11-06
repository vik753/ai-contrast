"""Keyword tags (ADR 0018 point 2): synonyms of confirmed topics on the skeleton view.

Heading and text are scanned separately and never joined into one phrase. Linear time.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol

from app.tagging.model import TagClause, ensure_unique_ids
from app.tagging.phrases import DEFAULT_BUDGET, Budget, PhraseIndex, match_view

__all__ = ["KEYWORD_RULES_VERSION", "KeywordTopic", "keyword_tags"]

# Bump when the matching rules change (read at call time by ``tagging_version``).
KEYWORD_RULES_VERSION: Final = "kw-1"


class KeywordTopic(Protocol):
    """What the matcher reads of a topic (a ``ConfirmedTopic`` has all of it)."""

    @property
    def topic_id(self) -> str: ...
    @property
    def synonyms_en(self) -> Sequence[str]: ...
    @property
    def synonyms_uk(self) -> Sequence[str]: ...
    @property
    def synonyms_ru(self) -> Sequence[str]: ...


def keyword_tags(
    clauses: Sequence[TagClause],
    topics: Sequence[KeywordTopic],
    *,
    budget_steps: int = DEFAULT_BUDGET,
) -> dict[str, set[str]]:
    """Topic ids per clause id; every clause id is a key (empty set: no tag).

    Raises ``TagMergeError`` (``duplicate_clause_id``, ``keyword_budget_exceeded``).
    """
    ensure_unique_ids(clauses)
    budget = Budget(budget_steps)
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
                found |= index.find_keys(match_view(part), budget)
    return result
