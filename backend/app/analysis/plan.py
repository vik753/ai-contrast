"""Input and plan of one analysis (ADR 0019 points 1, 4 and 7).

Everything that touches gate types lives here and in ``run``, not in the route module. The
tag signature is checked, the tags are rebuilt from recomputed keyword tags, signed model and
check tags and client tags (``merge_tags``), then the call sets, the worst-case calls and
Neurons are planned. Raises ``JobRefusedError`` (a code only). Nothing here logs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.ai.port import OutputLanguage
from app.ai.prompts import PromptTemplate
from app.analysis.rate import other_max_tokens, topic_max_tokens
from app.analysis.schemas import OtherRatingOut, TopicRatingOut
from app.analysis.verify import (
    Clause,
    DocFlag,
    DocumentIndex,
    TopicState,
    build_document_index,
    other_clause_ids,
)
from app.analysis.verify.index import ClauseInfo
from app.analysis.verify.rules import MAX_REFS
from app.extraction.references import mentions_external_document
from app.limits.free import topic_neurons
from app.pseudo.gate import ConfirmedTopic
from app.settings import Settings
from app.tagging.batches import plan_batches
from app.tagging.clauses import clauses_of
from app.tagging.merge import TaggingResult, merge_tags
from app.tagging.model import TagMergeError
from app.tagging.risk_terms import scan_risk
from app.tagging.run import JobRefusedError, TagJob
from app.tagging.signature import SignedTopic, TagSigner, tag_binding, topic_fingerprint
from app.tagging.version import tagging_version

__all__ = [
    "TOPIC_MAX_CHARS",
    "TOPIC_MAX_CLAUSES",
    "AnalysisPlan",
    "AnalysisRequest",
    "DocFacts",
    "SignedStatus",
    "TopicPlan",
    "make_facts",
    "plan_analysis",
    "recompute_tags",
    "verify_tagging",
]

TOPIC_MAX_CLAUSES: Final = 40
TOPIC_MAX_CHARS: Final = 20_000
SIGNATURE_INVALID: Final = "tagging_signature_invalid"
TOO_LARGE: Final = "document_too_large_for_analysis"
_NUMBER: Final = re.compile(r"\s*(\d{1,3}(?:\.\d{1,3})+|\d{1,3}(?=[.)]\s))")
_CLAUSE_OVERHEAD: Final = 12
_PROMPT_OVERHEAD: Final = 800
_CYRILLIC_NUM: Final = 3
_CYRILLIC_DEN: Final = 2


@dataclass(frozen=True)
class SignedStatus:
    model_tags_dropped: bool
    not_analyzed: str | None


@dataclass(frozen=True)
class AnalysisRequest:
    """The plain data of the request (no gate type)."""

    domain: str
    side: str
    language: OutputLanguage
    model: str
    flags: frozenset[DocFlag]
    annex_links: frozenset[str]
    reasons: tuple[str, ...]
    signed_tags: Mapping[str, Mapping[str, str]]  # clause -> topic -> source (as sent)
    status: Mapping[str, SignedStatus]
    client_tags: Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class DocFacts:
    """What verification needs about the document (source texts, index, Layer 2)."""

    clauses: tuple[Clause, ...]
    index: DocumentIndex
    unprovided: frozenset[str]
    layer2_spans: tuple[tuple[str, int, int], ...]
    layer2_heuristic: frozenset[str]
    layer2_high: bool


@dataclass(frozen=True)
class TopicPlan:
    topic: ConfirmedTopic
    tagged: tuple[str, ...]
    sent: tuple[str, ...]
    state: TopicState
    reason: str | None  # why it is not analyzed before any call
    essential: bool

    @property
    def callable(self) -> bool:
        return bool(self.tagged) and self.state is not TopicState.not_analyzed


@dataclass(frozen=True)
class AnalysisPlan:
    topics: tuple[TopicPlan, ...]
    other: tuple[str, ...]
    other_batches: int
    max_other_batches: int
    topic_calls: int
    calls: int
    neurons: int
    complete: bool  # the signed tagging had no incomplete reason


def _number_of(text: str) -> str | None:
    match = _NUMBER.match(text)
    return match.group(1) if match else None


def make_facts(job: TagJob, req: AnalysisRequest) -> DocFacts:
    """Raises ``JobRefusedError("invalid_annex_link")`` for an unknown clause id."""
    known = {c.id for c in job.document.clauses}
    if not req.annex_links <= known:
        raise JobRefusedError("invalid_annex_link", 422)
    clauses = tuple(Clause(c.id, c.text, "", _number_of(c.text)) for c in job.document.clauses)
    spans: list[tuple[str, int, int]] = []
    heuristic: set[str] = set()
    high = False
    for cid, hits in job.child.layer2.items():
        for start, end, cls in hits.text:
            spans.append((cid, start, end))
            if cls == "high":
                high = True
            else:
                heuristic.add(cid)
    unprovided = frozenset(c.id for c in clauses if mentions_external_document(c.text))
    return DocFacts(
        clauses,
        _with_annex(build_document_index(clauses), unprovided & req.annex_links),
        unprovided - req.annex_links,
        tuple(spans),
        frozenset(heuristic),
        high,
    )


def _with_annex(index: DocumentIndex, linked: frozenset[str]) -> DocumentIndex:
    """A client annex link lifts the unresolved-reference cap of a clause that names another
    document (the client states that the document is provided). Nothing else changes."""
    if not linked:
        return index
    info = dict(index.info)
    for cid in linked:
        old = info[cid]
        info[cid] = ClauseInfo(old.exception, old.override, False, old.refs, old.heading_refs)
    return DocumentIndex(
        by_id=index.by_id,
        info=info,
        numbers=index.numbers,
        overrides=index.overrides,
        inbound=index.inbound,
        ranges=index.ranges,
        scaled=index.scaled,
    )


def _signed_topics(job: TagJob, req: AnalysisRequest) -> list[SignedTopic] | None:
    out: list[SignedTopic] = []
    for topic in job.plan.topics:
        status = req.status.get(topic.topic_id)
        if status is None:
            return None
        out.append(
            SignedTopic(
                topic.topic_id,
                topic_fingerprint(topic),
                status.model_tags_dropped,
                status.not_analyzed,
            )
        )
    return out


def verify_tagging(  # noqa: PLR0913, PLR0917
    signer: TagSigner, job: TagJob, req: AnalysisRequest, digest: str, version: str, signature: str
) -> None:
    """Raise ``JobRefusedError("tagging_signature_invalid", 409)`` unless the signature is the
    one this process gave for exactly this document, version, tags, status and topic set."""
    signed = _signed_topics(job, req)
    if signed is None or digest != job.child.digest or version != tagging_version():
        raise JobRefusedError(SIGNATURE_INVALID, 409)
    binding = tag_binding(reasons=req.reasons, topics=signed, domain=req.domain, side=req.side)
    if not signer.verify(
        signature,
        digest=digest,
        tagging_version=version,
        tags=req.signed_tags,
        binding=binding,
    ):
        raise JobRefusedError(SIGNATURE_INVALID, 409)


def recompute_tags(job: TagJob, req: AnalysisRequest) -> TaggingResult:
    """Keyword tags recomputed, model and check tags from the signed pairs, client tags added."""
    high: dict[str, set[str]] = {}
    low: dict[str, set[str]] = {}
    yes: dict[str, set[str]] = {}
    for clause_id, by_topic in req.signed_tags.items():
        for topic_id, source in by_topic.items():
            if source == "model":
                high.setdefault(clause_id, set()).add(topic_id)
            elif source == "check":
                low.setdefault(clause_id, set()).add(topic_id)
                yes.setdefault(clause_id, set()).add(topic_id)
    try:
        return merge_tags(
            clauses=clauses_of(job.document),
            topics=job.plan.topics,
            keyword=job.child.keyword_sets(),
            model_high=high,
            model_low=low,
            check_yes=yes,
            client={c: set(t) for c, t in req.client_tags.items()},
        )
    except TagMergeError as error:
        raise JobRefusedError(error.code, 422) from None


def _essential(catalog_topic_id: str, domain: str, side: str, catalog: object) -> bool:
    domains = getattr(catalog, "domains", ())
    for d in domains:
        if d.id != domain:
            continue
        for t in d.topics:
            if t.id == catalog_topic_id:
                return bool(t.essential and t.essential.get(side))
    return False


def pack(ids: Sequence[str], size: Mapping[str, int]) -> list[tuple[str, ...]]:
    """Consecutive batches of ids (at most 40 clauses and 12,000 characters)."""
    ranges = plan_batches([size[i] for i in ids])
    return [tuple(ids[a:b]) for a, b in ranges]


def _call_neurons(chars: int, max_tokens: int) -> int:
    scaled = -(-chars * _CYRILLIC_NUM // _CYRILLIC_DEN)
    return topic_neurons(scaled, max_tokens, repair=True)


def _schema_chars(model: type[TopicRatingOut] | type[OtherRatingOut]) -> int:
    return len(json.dumps(model.model_json_schema(), separators=(",", ":")))


def _topic_plan(  # noqa: PLR0913, PLR0917
    topic: ConfirmedTopic,
    result: TaggingResult,
    req: AnalysisRequest,
    facts: DocFacts,
    catalog: object,
    size: Mapping[str, int],
) -> TopicPlan:
    tid = topic.topic_id
    tagged = tuple(c.id for c in facts.clauses if tid in result.tags[c.id])
    signed = req.status[tid]
    essential = _essential(tid, req.domain, req.side, catalog)
    if signed.not_analyzed or result.topics[tid].not_analyzed:
        return TopicPlan(topic, tagged, (), TopicState.not_analyzed, "too_many_clauses", essential)
    chars = sum(size[i] for i in tagged)
    if len(tagged) > TOPIC_MAX_CLAUSES or chars > TOPIC_MAX_CHARS:
        return TopicPlan(topic, tagged, (), TopicState.not_analyzed, "topic_call_cap", essential)
    state = TopicState.model_tags_dropped if signed.model_tags_dropped else TopicState.ok
    sent = list(tagged)
    seen = set(tagged)
    for cid in tagged:
        entry = facts.index.numbers.resolve(facts.index.info[cid].refs, cid, MAX_REFS)
        for added in entry.added:
            if (
                added not in seen
                and len(seen) < TOPIC_MAX_CLAUSES
                and chars + size[added] <= TOPIC_MAX_CHARS
            ):
                seen.add(added)
                chars += size[added]
                sent.append(added)
    order = {c.id: i for i, c in enumerate(facts.clauses)}
    sent.sort(key=order.__getitem__)
    return TopicPlan(topic, tagged, tuple(sent), state, None, essential)


def plan_analysis(  # noqa: PLR0913, PLR0917
    job: TagJob,
    req: AnalysisRequest,
    result: TaggingResult,
    facts: DocFacts,
    catalog: object,
    settings: Settings,
) -> AnalysisPlan:
    size = {c.id: len(c.text) for c in facts.clauses}
    topics = tuple(_topic_plan(t, result, req, facts, catalog, size) for t in job.plan.topics)
    gone = {p.topic.topic_id for p in topics if p.state is TopicState.not_analyzed}
    moved = other_clause_ids(result.other, {p.topic.topic_id: p.tagged for p in topics}, gone)
    risky = [c for c in moved if c in result.risk or scan_risk(_text(facts, c))]
    risky_set = set(risky)
    other = tuple(risky) + tuple(c for c in moved if c not in risky_set)
    callable_topics = [p for p in topics if p.callable]
    union = list(dict.fromkeys([*other, *(c for p in callable_topics for c in p.tagged)]))
    batches_all = pack(union, size)
    calls = 2 * len(callable_topics) + 2 * len(batches_all)
    if calls > settings.analysis_max_calls or sum(size.values()) > settings.tag_max_document_chars:
        raise JobRefusedError(TOO_LARGE, 422)
    topic_base = len(PromptTemplate.RATE_TOPIC.value) + _schema_chars(TopicRatingOut)
    other_base = len(PromptTemplate.RATE_OTHER.value) + _schema_chars(OtherRatingOut)
    neurons = 0
    for p in callable_topics:
        text = sum(size[i] + _CLAUSE_OVERHEAD for i in p.sent)
        info = len(p.topic.title) + len(p.topic.description) + 200 * len(p.topic.attributes)
        neurons += _call_neurons(
            topic_base + _PROMPT_OVERHEAD + info + text, topic_max_tokens(p.topic)
        )
    for batch in batches_all:
        text = sum(size[i] + _CLAUSE_OVERHEAD for i in batch)
        neurons += _call_neurons(other_base + _PROMPT_OVERHEAD + text, other_max_tokens(len(batch)))
    return AnalysisPlan(
        topics=topics,
        other=other,
        other_batches=len(pack(list(other), size)),
        max_other_batches=len(batches_all),
        topic_calls=len(callable_topics),
        calls=calls,
        neurons=max(1, neurons),
        complete=not req.reasons,
    )


def _text(facts: DocFacts, clause_id: str) -> str:
    return facts.index.by_id[clause_id].text
