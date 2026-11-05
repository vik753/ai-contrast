"""Merge of keyword, model, check and client tags with the caps of ADR 0018 point 5.

Rules: keyword and client tags are never removed. Model and check tags only add; they are
capped per clause (5) and per topic (60 clauses, then all model tags of the topic are
dropped). A topic with more than 120 keyword or client clauses is ``not_analyzed``. A
clause without a usable tag goes to "Other". Never a clause is lost.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Final, Literal, get_args

from app.pseudo.gate import ConfirmedTopic
from app.tagging.model import TagClause, TagMergeError, ensure_unique_ids
from app.tagging.risk_terms import scan_risk

__all__ = ["TaggingResult", "TopicStatus", "merge_tags"]

_log = logging.getLogger(__name__)

MAX_MODEL_TAGS_PER_CLAUSE: Final = 5
MAX_CLIENT_TAGS_PER_CLAUSE: Final = 5
MAX_MODEL_CLAUSES_PER_TOPIC: Final = 60
MAX_KEYWORD_CLAUSES_PER_TOPIC: Final = 120
CHECK_FAILED: Final = "check_failed"

Pairs = Mapping[str, Set[str]]
Source = Literal["keyword", "model", "check", "client"]
Failure = Literal["bad_output", "timeout", "quota", "check_failed"]
Reason = Literal["bad_output", "timeout", "quota", "check_failed", "clause_cap"]
_FAILURES: Final = frozenset(get_args(Failure))


@dataclass(frozen=True, slots=True)
class TopicStatus:
    """``keyword_clauses``: clauses with a keyword or client tag. ``model_asserted``: all
    model and check pairs seen (also those on keyword-tagged clauses). ``model_clauses``:
    clauses whose tag has the source model or check (0 after a drop)."""

    keyword_clauses: int
    model_asserted: int
    model_clauses: int
    model_tags_dropped: bool
    not_analyzed: str | None


@dataclass(frozen=True, slots=True)
class TaggingResult:
    """The merged tags of one document.

    ``tags``: every clause id -> ``{topic_id: source}``. ``other``: ids (document order) of
    clauses without a usable tag. ``risk``: one key for **every** "Other" clause with a
    risk-term hit in its text or heading; the value holds the text spans and may be empty
    (heading-only hit). ``risk_heading``: heading spans for the same clauses.

    Caps: at most 5 model/check tags per clause and, separately, at most 5 client tags per
    clause (refused above); keyword tags are not capped. Overflow of the per-clause model
    cap adds the reason ``clause_cap``.
    """

    tags: dict[str, dict[str, Source]]
    other: list[str]
    risk: dict[str, list[tuple[int, int]]]
    risk_heading: dict[str, list[tuple[int, int]]]
    topics: dict[str, TopicStatus]
    model_tagging_incomplete: bool
    incomplete_reasons: tuple[Reason, ...]
    missing_topics: tuple[str, ...]


def _check_client(client: Pairs, clause_ids: Set[str], topic_ids: Set[str]) -> None:
    for clause_id, topic_set in client.items():
        if clause_id not in clause_ids or any(t not in topic_ids for t in topic_set):
            raise TagMergeError("invalid_client_tag")
        if len(topic_set) > MAX_CLIENT_TAGS_PER_CLAUSE:
            raise TagMergeError("too_many_client_tags")


def _model_candidates(  # noqa: PLR0913, PLR0917
    clause_ids: Sequence[str],
    topic_order: Mapping[str, int],
    keyword: Pairs,
    high: Pairs,
    low: Pairs,
    check_yes: Pairs,
    *,
    check_ok: bool,
) -> tuple[dict[str, dict[str, Source]], bool]:
    """Model and check pairs per clause after the per-clause cap (5, high before low, then
    topic order). Pairs that are also keyword tags do not use a slot. The flag tells that
    a clause had more pairs than slots."""
    result: dict[str, dict[str, Source]] = {}
    overflow = False
    for clause_id in clause_ids:
        pairs: dict[str, Source] = {}
        for topic_id in high.get(clause_id, ()):
            if topic_id in topic_order:
                pairs[topic_id] = "model"
        if check_ok:
            confirmed = check_yes.get(clause_id, set())
            for topic_id in low.get(clause_id, ()):
                if topic_id in topic_order and topic_id in confirmed:
                    pairs.setdefault(topic_id, "check")
        if not pairs:
            continue
        own = keyword.get(clause_id, set())
        ranked = sorted(pairs.items(), key=lambda item: (item[1] != "model", topic_order[item[0]]))
        kept: dict[str, Source] = {}
        slots = 0
        for topic_id, source in ranked:
            if topic_id in own:
                kept[topic_id] = source
            elif slots < MAX_MODEL_TAGS_PER_CLAUSE:
                kept[topic_id] = source
                slots += 1
            else:
                overflow = True
        result[clause_id] = kept
    return result, overflow


def merge_tags(  # noqa: PLR0913, PLR0912
    *,
    clauses: Sequence[TagClause],
    topics: Sequence[ConfirmedTopic],
    keyword: Pairs,
    model_high: Pairs | None = None,
    model_low: Pairs | None = None,
    check_yes: Pairs | None = None,
    client: Pairs | None = None,
    failures: Sequence[Failure] = (),
) -> TaggingResult:
    ensure_unique_ids(clauses)
    if any(f not in _FAILURES for f in failures):
        raise TagMergeError("invalid_failure")
    clause_ids = [c.id for c in clauses]
    topic_order = {t.topic_id: i for i, t in enumerate(topics)}
    client = client or {}
    _check_client(client, set(clause_ids), set(topic_order))
    reasons_set: set[Reason] = set(failures)
    candidates, overflow = _model_candidates(
        clause_ids,
        topic_order,
        keyword,
        model_high or {},
        model_low or {},
        check_yes or {},
        check_ok="check_failed" not in reasons_set,
    )
    if overflow:
        reasons_set.add("clause_cap")
    reasons = tuple(sorted(reasons_set))

    # Per topic cap: only model pairs that add a clause (no keyword tag there) count; too
    # many drop every model tag of the topic.
    asserted: dict[str, int] = dict.fromkeys(topic_order, 0)
    adding: dict[str, int] = dict.fromkeys(topic_order, 0)
    for clause_id, pairs in candidates.items():
        own = keyword.get(clause_id, set())
        for topic_id in pairs:
            asserted[topic_id] += 1
            if topic_id not in own:
                adding[topic_id] += 1
    dropped = {t for t, n in adding.items() if n > MAX_MODEL_CLAUSES_PER_TOPIC}

    keyword_count: dict[str, int] = dict.fromkeys(topic_order, 0)
    tags: dict[str, dict[str, Source]] = {}
    for clause_id in clause_ids:
        own = {t for t in keyword.get(clause_id, ()) if t in topic_order}
        mine = {t for t in client.get(clause_id, ()) if t in topic_order}
        model = candidates.get(clause_id, {})
        merged: dict[str, Source] = {}
        for topic_id in sorted(own | mine | set(model), key=topic_order.__getitem__):
            if topic_id in own:
                merged[topic_id] = "keyword"
            elif topic_id in model and topic_id not in dropped:
                merged[topic_id] = model[topic_id]
            elif topic_id in mine:
                merged[topic_id] = "client"
        for topic_id in own | mine:
            keyword_count[topic_id] += 1
        tags[clause_id] = merged

    not_analyzed = {t for t, n in keyword_count.items() if n > MAX_KEYWORD_CLAUSES_PER_TOPIC}
    other = [c for c in clause_ids if not any(t not in not_analyzed for t in tags[c])]

    by_id = {c.id: c for c in clauses}
    risk: dict[str, list[tuple[int, int]]] = {}
    risk_heading: dict[str, list[tuple[int, int]]] = {}
    for clause_id in other:
        clause = by_id[clause_id]
        text_hits = scan_risk(clause.text)
        heading_hits = scan_risk(clause.heading) if clause.heading else []
        if text_hits or heading_hits:
            risk[clause_id] = text_hits
        if heading_hits:
            risk_heading[clause_id] = heading_hits

    status: dict[str, TopicStatus] = {}
    for topic_id in topic_order:
        modelled = sum(1 for t in tags.values() if t.get(topic_id) in {"model", "check"})
        status[topic_id] = TopicStatus(
            keyword_clauses=keyword_count[topic_id],
            model_asserted=asserted[topic_id],
            model_clauses=modelled,
            model_tags_dropped=topic_id in dropped,
            not_analyzed="too_many_clauses" if topic_id in not_analyzed else None,
        )

    # Incomplete tagging (including a clause cap overflow) never yields a missing topic.
    missing = (
        ()
        if reasons
        else tuple(
            t
            for t in topic_order
            if t not in dropped
            and t not in not_analyzed
            and not any(t in clause_tags for clause_tags in tags.values())
        )
    )
    _log.info(
        "tagging merged clauses=%d other=%d risk=%d incomplete=%d missing=%d",
        len(clause_ids),
        len(other),
        len(risk),
        len(reasons),
        len(missing),
    )
    return TaggingResult(
        tags=tags,
        other=other,
        risk=risk,
        risk_heading=risk_heading,
        topics=status,
        model_tagging_incomplete=bool(reasons),
        incomplete_reasons=reasons,
        missing_topics=missing,
    )
