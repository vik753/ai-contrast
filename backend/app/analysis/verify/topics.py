"""Missing-topic findings, Other completeness, not_analyzed routing (ADR 0019 points 3.5-3.7)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from app.analysis.verify.model import (
    Completeness,
    MissingTopicFinding,
    Rating,
    TaggingState,
    TopicInfo,
    TopicState,
)

__all__ = ["document_completeness", "missing_topic_findings", "other_clause_ids"]


def missing_topic_findings(
    tagging: TaggingState, topics: Sequence[TopicInfo]
) -> tuple[MissingTopicFinding, ...]:
    """Yellow, or red for an essential topic, for a topic with no clause. Never green.
    Incomplete or unsigned tagging gives nothing (fail closed)."""
    if not (tagging.complete and tagging.signed):
        return ()
    return tuple(
        MissingTopicFinding(t.id, Rating.red if t.essential else Rating.yellow)
        for t in topics
        if t.clause_count == 0 and t.state is TopicState.ok
    )


def document_completeness(other_total: int, other_rated: int) -> Completeness:
    if other_total < 0 or other_rated < 0:
        raise ValueError("negative_count")  # noqa: TRY003
    unrated = max(0, other_total - other_rated)
    return Completeness(unrated > 0, unrated, unrated == 0)


def other_clause_ids(
    tagged_other: Sequence[str],
    topic_clauses: Mapping[str, Sequence[str]],
    not_analyzed: Collection[str],
) -> tuple[str, ...]:
    """Other clauses first, then the clauses of ``not_analyzed`` topics; no duplicates."""
    result: dict[str, None] = dict.fromkeys(tagged_other)
    for topic, ids in topic_clauses.items():
        if topic in not_analyzed:
            result.update(dict.fromkeys(ids))
    return tuple(result)
