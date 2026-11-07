"""The tagging job (ADR 0018): plan, sandbox step, model steps, merge and reply.

Everything that touches gate types lives here, not in the route module (``app/api/tag.py``).
The route builds the providers and answers; this module never imports an endpoint. Nothing
here logs text; the merge logs counts only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Final

from app.ai.port import AIError, AIErrorCode, AIProvider
from app.extraction.sandbox import SandboxLimits
from app.limits.free import reported_neurons
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument, SafetyError, safety_pass
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.settings import Settings
from app.tagging.ai_steps import ModelState, run_model_steps
from app.tagging.batches import MAX_BATCHES, plan_batches, worst_case
from app.tagging.child import ChildTopic
from app.tagging.clauses import clauses_of
from app.tagging.merge import Failure, Reason, TaggingResult, merge_tags
from app.tagging.model import TagClause
from app.tagging.runner import TagChildOk, run_tag_child
from app.tagging.signature import SignedTopic, TagSigner, tag_binding, topic_fingerprint
from app.tagging.version import tagging_version
from app.topics.catalog import Catalog
from app.topics.selection import TopicSelection, resolve_topics

__all__ = [
    "JobPlan",
    "JobRefusedError",
    "Outcome",
    "TagJob",
    "finish_tags",
    "model_phase",
    "plan_job",
    "prepare_job",
    "run_tagging",
]

INVALID_DEFINITION: Final = "invalid_topic_definition"
# Failures passed to ``merge_tags``. A failed check is not: ``merge_tags`` would then drop the
# check tags of every batch, but ADR 0018 point 3 drops only the low tags of the failed check
# call (``run_model_steps`` never records them). ``finish_tags`` adds the reason afterwards.
_MERGE_FAILURES: Final[tuple[Failure, ...]] = ("bad_output", "timeout", "quota")
CHECK_FAILED: Final[Reason] = "check_failed"


class JobRefusedError(Exception):
    """The request is refused with ``code`` and HTTP ``status``. Holds no data."""

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class JobPlan:
    """Topics, batches and the worst case ``(calls, Neurons)`` of one request."""

    topics: tuple[ConfirmedTopic, ...]
    batches: tuple[tuple[str, ...], ...]
    calls: int
    neurons: int
    chars: int
    domain: str = ""
    side: str = ""


@dataclass(frozen=True)
class TagJob:
    plan: JobPlan
    document: PseudonymizedDocument
    child: TagChildOk


@dataclass(frozen=True)
class Outcome:
    """Reply or hard provider error (``hard``), AI calls made, Neurons to charge."""

    reply: dict[str, object] | None
    hard: AIErrorCode | None = None
    calls: int = 0
    spent: int = 0


def plan_job(  # noqa: PLR0913, PLR0917
    document: UntrustedMaskedDocument,
    selection: TopicSelection,
    catalog: Catalog,
    settings: Settings,
    domain: str,
    side: str,
) -> JobPlan:
    """Resolve the topics and check the size limits. Raises ``JobRefusedError`` (or the topic errors
    of ``resolve_topics``). Nothing is counted."""
    if not catalog.has_side(domain, side):
        raise JobRefusedError(INVALID_DEFINITION)
    topics = resolve_topics(selection, catalog)
    if not topics:
        raise JobRefusedError("no_topics")
    if len({topic.topic_id for topic in topics}) != len(topics):
        raise JobRefusedError("duplicate_topic")
    lengths = [len(clause.text) for clause in document.clauses]
    chars = sum(lengths)
    ranges = plan_batches(lengths)
    if chars > settings.tag_max_document_chars or len(ranges) > MAX_BATCHES:
        raise JobRefusedError("document_too_large_for_tagging")
    ids = [clause.id for clause in document.clauses]
    batches = tuple(tuple(ids[start:end]) for start, end in ranges)
    calls, neurons = worst_case(ranges, lengths, topics)
    return JobPlan(topics, batches, calls, neurons, chars, domain, side)


async def prepare_job(
    plan: JobPlan, document: UntrustedMaskedDocument, settings: Settings, limits: SandboxLimits
) -> TagJob:
    """Run the sandbox child, then make the gate object (it can only be made in this process,
    so the same pass runs here, in a thread, on the same already accepted input).

    Raises ``SafetyRunError`` (also ``keyword_budget_exceeded``) or ``JobRefusedError``."""
    child_topics = [
        ChildTopic(
            topic_id=topic.topic_id,
            synonyms_en=list(topic.synonyms_en),
            synonyms_uk=list(topic.synonyms_uk),
            synonyms_ru=list(topic.synonyms_ru),
        )
        for topic in plan.topics
    ]
    child = await run_tag_child(
        document,
        child_topics,
        keyword_budget=settings.keyword_step_budget,
        limits=limits,
        max_clauses=settings.segment_max_clauses,
    )
    try:
        checked = await asyncio.to_thread(
            safety_pass, document, max_clauses=settings.segment_max_clauses
        )
    except SafetyError:
        raise JobRefusedError("safety_failed") from None
    return TagJob(plan, checked, child)


def _spent(providers: Sequence[AIProvider], model: ModelState, worst: int) -> int:
    """Neurons to charge: the reported usage when every call completed and reported it; else the
    worst case of the request (a timeout, a transport error or a cancelled call reports nothing)."""
    if model.calls == 0:
        return 0
    if model.completed < model.calls:
        return worst
    total = 0
    for provider in providers:
        reported = reported_neurons(provider)
        if reported is None:
            return worst
        total += reported
    return total


def _reply(signer: TagSigner, job: TagJob, result: TaggingResult) -> dict[str, object]:
    reasons = set(result.incomplete_reasons)
    version = tagging_version()
    digest = job.child.digest
    signed = [
        SignedTopic(
            topic.topic_id,
            topic_fingerprint(topic),
            result.topics[topic.topic_id].model_tags_dropped,
            result.topics[topic.topic_id].not_analyzed,
        )
        for topic in job.plan.topics
    ]
    signature = signer.sign(
        digest=digest,
        tagging_version=version,
        tags={clause_id: dict(by_topic) for clause_id, by_topic in result.tags.items()},
        binding=tag_binding(
            reasons=reasons, topics=signed, domain=job.plan.domain, side=job.plan.side
        ),
    )
    return {
        "digest": digest,
        "tagging_version": version,
        "signature": signature,
        "tags": {
            clause_id: [{"topic_id": topic, "source": source} for topic, source in by_topic.items()]
            for clause_id, by_topic in result.tags.items()
        },
        "other": result.other,
        "risk": {
            clause_id: [list(span) for span in spans] for clause_id, spans in result.risk.items()
        },
        "topics": {
            topic_id: {
                "keyword_clauses": status.keyword_clauses,
                "model_clauses": status.model_clauses,
                "model_asserted": status.model_asserted,
                "model_tags_dropped": status.model_tags_dropped,
                "not_analyzed": status.not_analyzed,
            }
            for topic_id, status in result.topics.items()
        },
        "missing_topics": [] if reasons else list(result.missing_topics),
        "layer2": {
            clause_id: {
                "text": [list(hit) for hit in hits.text],
                "heading": [list(hit) for hit in hits.heading],
            }
            for clause_id, hits in job.child.layer2.items()
        },
        "model_tagging_incomplete": bool(reasons),
        "incomplete_reasons": sorted(reasons),
    }


async def model_phase(  # noqa: PLR0913, PLR0917
    state: ModelState,
    document: PseudonymizedDocument,
    topics: Sequence[ConfirmedTopic],
    batches: Sequence[Sequence[str]],
    tag_provider: AIProvider,
    check_provider: AIProvider,
    *,
    deadline: float,
    call_deadline: float,
) -> None:
    """The model steps under the overall deadline, writing into ``state``. A deadline hit adds
    ``timeout`` and keeps what the finished calls found; a hard provider error is raised as
    ``AIError`` and ``state`` still holds the call counts (for charging)."""
    try:
        async with asyncio.timeout(deadline):
            await run_model_steps(
                document, topics, batches, tag_provider, check_provider, state, call_deadline
            )
    except TimeoutError:
        state.failures.add("timeout")


def finish_tags(
    clauses: Sequence[TagClause],
    topics: Sequence[ConfirmedTopic],
    keyword: Mapping[str, Set[str]],
    model: ModelState,
) -> TaggingResult:
    """The merge after the AI calls (pure): caps, "Other", risk terms and the incomplete
    reasons, including ``check_failed`` (then no missing-topic finding)."""
    result = merge_tags(
        clauses=clauses,
        topics=topics,
        keyword=keyword,
        model_high=model.high,
        model_low=model.low,
        check_yes=model.check_yes,
        failures=[f for f in _MERGE_FAILURES if f in model.failures],
    )
    if CHECK_FAILED not in model.failures:
        return result
    reasons = tuple(sorted({*result.incomplete_reasons, CHECK_FAILED}))
    # A new value, not ``dataclasses.replace`` (banned in modules that use gate types).
    return TaggingResult(
        tags=result.tags,
        other=result.other,
        risk=result.risk,
        risk_heading=result.risk_heading,
        topics=result.topics,
        model_tagging_incomplete=True,
        incomplete_reasons=reasons,
        missing_topics=(),
    )


async def run_tagging(
    job: TagJob,
    tag_provider: AIProvider,
    check_provider: AIProvider,
    settings: Settings,
    signer: TagSigner,
) -> Outcome:
    """The model steps under the overall deadline, the merge and the reply."""
    providers = [tag_provider] if check_provider is tag_provider else [tag_provider, check_provider]
    model = ModelState()
    try:
        await model_phase(
            model,
            job.document,
            job.plan.topics,
            job.plan.batches,
            tag_provider,
            check_provider,
            deadline=settings.tag_deadline_seconds,
            call_deadline=settings.tag_call_deadline_seconds,
        )
    except AIError as error:
        return Outcome(
            None, error.code, model.calls, _spent(providers, model, job.plan.neurons) or 0
        )
    result = await asyncio.to_thread(
        finish_tags, clauses_of(job.document), job.plan.topics, job.child.keyword_sets(), model
    )
    spent = _spent(providers, model, job.plan.neurons)
    return Outcome(_reply(signer, job, result), None, model.calls, spent)
