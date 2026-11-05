"""Strict output schemas of the two tagging calls (ADR 0018 point 3) and their checks.

A schema is the shape only. ``checked_tags`` and ``checked_answers`` compare an answer with
what was asked (clause ids, topic indexes, pairs); any difference is ``BadOutputError``. A cap
that is broken fails the whole answer (no truncation).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MAX_TAGS_PER_CLAUSE",
    "BadOutputError",
    "CheckOut",
    "TagOut",
    "checked_answers",
    "checked_tags",
]

MAX_TAGS_PER_CLAUSE: Final = 5
MAX_ITEMS: Final = 400

ClauseRef = Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,3}$")]
TopicRef = Annotated[str, Field(pattern=r"^T[1-9][0-9]{0,2}$")]


class BadOutputError(Exception):
    """The model answer is unusable (after the repair attempt). Holds no data."""


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TagTopicOut(_Out):
    index: TopicRef
    confidence: Literal["high", "low"]


class TagClauseOut(_Out):
    clause: ClauseRef
    topics: Annotated[list[TagTopicOut], Field(max_length=MAX_TAGS_PER_CLAUSE)]


class TagOut(_Out):
    tags: Annotated[list[TagClauseOut], Field(max_length=MAX_ITEMS)]


class AnswerOut(_Out):
    clause: ClauseRef
    topic: TopicRef
    regulates: bool


class CheckOut(_Out):
    answers: Annotated[list[AnswerOut], Field(max_length=MAX_ITEMS)]


def checked_tags(
    out: TagOut, clause_ids: Collection[str], topic_count: int
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """``(high, low)``: topic numbers per clause id. Unknown clause or index, a clause or an
    index listed twice: ``BadOutputError``."""
    high: dict[str, set[int]] = {}
    low: dict[str, set[int]] = {}
    seen: set[str] = set()
    for item in out.tags:
        if item.clause not in clause_ids or item.clause in seen:
            raise BadOutputError
        seen.add(item.clause)
        numbers = [int(t.index[1:]) for t in item.topics]
        if len(set(numbers)) != len(numbers) or any(not 1 <= n <= topic_count for n in numbers):
            raise BadOutputError
        for topic in item.topics:
            target = high if topic.confidence == "high" else low
            target.setdefault(item.clause, set()).add(int(topic.index[1:]))
    return high, low


def checked_answers(out: CheckOut, asked: Sequence[tuple[str, int]]) -> set[tuple[str, int]]:
    """The asked pairs answered ``true``. An unasked or repeated pair: ``BadOutputError``.
    An asked pair without an answer is not confirmed."""
    allowed = set(asked)
    seen: set[tuple[str, int]] = set()
    yes: set[tuple[str, int]] = set()
    for answer in out.answers:
        pair = (answer.clause, int(answer.topic[1:]))
        if pair not in allowed or pair in seen:
            raise BadOutputError
        seen.add(pair)
        if answer.regulates:
            yes.add(pair)
    return yes
