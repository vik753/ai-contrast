"""The two rating calls (ADR 0019 point 2): one document and one topic, or the clauses that no
topic covers. Each call checks the answer against the request, cleans every explanation, makes
at most one repair call (a fixed error code, never the previous output) and raises
``BadOutputError`` after the second bad answer. Hard provider errors pass through. Nothing here
logs; no model text is kept beyond the validated answer."""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import ValidationError

from app.ai.port import (
    MAX_OUTPUT_TOKENS,
    REPAIR_CAP,
    REPAIR_NOT_JSON,
    REPAIR_SCHEMA,
    AIError,
    AIErrorCode,
    AIProvider,
    AIRequest,
    ModelJson,
    OutputLanguage,
    RateOtherRequest,
    RateTopicRequest,
    ReasoningEffort,
)
from app.ai.prompting import clause_refs
from app.ai.prompts import PromptTemplate
from app.analysis.schemas import (
    MAX_EXPLANATION,
    AmountValue,
    BadOutputError,
    CategoriesValue,
    DurationValue,
    EnumValue,
    EvidenceOut,
    FindingOut,
    NotStatedValue,
    OtherRatingOut,
    TextValue,
    TopicRatingOut,
)
from app.injection import scan
from app.pseudo.gate import ConfirmedAttribute, ConfirmedTopic, PseudonymizedDocument
from app.textclean import TextCleaner
from app.topics.catalog import Catalog

__all__ = [
    "EXPLANATION_WITHHELD",
    "clean_explanation",
    "other_max_tokens",
    "rate_other",
    "rate_topic",
    "topic_max_tokens",
]

EXPLANATION_WITHHELD = "explanation_withheld"
MAX_OTHER_CLAUSES = 40
_SIDE_RE = re.compile(r"[a-z][a-z0-9_]{1,47}", re.ASCII)
_CAP_TYPES = frozenset({"too_long", "string_too_long"})
ATTEMPTS = 2  # one call and one repair call
_FLOOR = 1024
# Reasoning models spend output tokens on thinking, so the budgets are generous.
_TOPIC_BASE = 3072
_TOPIC_PER_ATTRIBUTE = 160
_TOPIC_FINDINGS = 8 * 240
_OTHER_BASE = 2048
_OTHER_PER_CLAUSE = 150


def topic_max_tokens(topic: ConfirmedTopic) -> int:
    size = _TOPIC_BASE + _TOPIC_PER_ATTRIBUTE * len(topic.attributes) + _TOPIC_FINDINGS
    return max(_FLOOR, min(MAX_OUTPUT_TOKENS, size))


def other_max_tokens(clause_count: int) -> int:
    return max(_FLOOR, min(MAX_OUTPUT_TOKENS, _OTHER_BASE + _OTHER_PER_CLAUSE * clause_count))


def clean_explanation(text: str) -> str:
    """Layer 1 table, NFC, at most 400 code points; a Layer 2 hit or an empty text is withheld."""
    cleaned = TextCleaner().clean(text).strip()
    if not cleaned or scan(cleaned):
        return EXPLANATION_WITHHELD
    return cleaned[:MAX_EXPLANATION].strip() or EXPLANATION_WITHHELD


def _clean_finding(finding: FindingOut) -> FindingOut:
    return finding.model_copy(update={"explanation": clean_explanation(finding.explanation)})


async def _complete[ResultT](
    provider: AIProvider,
    make: Callable[[int], AIRequest],
    check: Callable[[ModelJson], ResultT],
) -> ResultT:
    repair = 0
    for _ in range(ATTEMPTS):
        try:
            raw = await provider.complete_json(make(repair))
        except AIError as error:
            if error.code is not AIErrorCode.PROVIDER_BAD_RESPONSE:
                raise
            repair = REPAIR_NOT_JSON
            continue
        try:
            return check(raw)
        except ValidationError as error:
            repair = (
                REPAIR_CAP
                if any(item["type"] in _CAP_TYPES for item in error.errors())
                else REPAIR_SCHEMA
            )
        except BadOutputError:
            repair = REPAIR_SCHEMA
    raise BadOutputError from None


def _check_evidence(items: list[EvidenceOut], clauses: set[str]) -> None:
    if any(item.clause not in clauses for item in items):
        raise BadOutputError


def _check_value(value: object, attribute: ConfirmedAttribute) -> None:
    if isinstance(value, NotStatedValue):
        return
    if value.type != attribute.type:  # type: ignore[attr-defined]
        raise BadOutputError
    if isinstance(value, AmountValue) and value.currency not in attribute.units:
        raise BadOutputError
    if isinstance(value, DurationValue) and value.unit not in attribute.units:
        raise BadOutputError
    if isinstance(value, EnumValue) and value.value not in attribute.value_ids:
        raise BadOutputError
    if isinstance(value, CategoriesValue) and (
        len(set(value.values)) != len(value.values)
        or not set(value.values) <= set(attribute.value_ids)
    ):
        raise BadOutputError


def _checked_topic(
    result: TopicRatingOut, clauses: set[str], topic: ConfirmedTopic
) -> TopicRatingOut:
    by_id = {attribute.id: attribute for attribute in topic.attributes}
    seen: set[str] = set()
    attributes = []
    for item in result.attributes:
        if item.attribute not in by_id or item.attribute in seen:
            raise BadOutputError
        seen.add(item.attribute)
        _check_value(item.value, by_id[item.attribute])
        if bool(item.evidence) == isinstance(item.value, NotStatedValue):
            raise BadOutputError  # a stated value needs evidence; not_stated has none
        _check_evidence(item.evidence, clauses)
        if isinstance(item.value, TextValue):
            value = item.value.model_copy(update={"text": clean_explanation(item.value.text)})
            item = item.model_copy(update={"value": value})  # noqa: PLW2901
        attributes.append(item)
    for finding in result.findings:
        if finding.attribute is not None and finding.attribute not in by_id:
            raise BadOutputError
        _check_evidence(finding.evidence, clauses)
    _check_evidence(result.injection_suspected, clauses)
    return result.model_copy(
        update={
            "attributes": attributes,
            "findings": [_clean_finding(finding) for finding in result.findings],
        }
    )


def _checked_other(result: OtherRatingOut, clauses: tuple[str, ...]) -> OtherRatingOut:
    answered = [item.clause for item in result.clauses]
    if len(set(answered)) != len(answered) or set(answered) != set(clauses):
        raise BadOutputError
    known = set(clauses)
    cleaned = []
    for item in result.clauses:
        for finding in item.findings:
            if finding.attribute is not None:
                raise BadOutputError
            _check_evidence(finding.evidence, known)
        cleaned.append(
            item.model_copy(update={"findings": [_clean_finding(f) for f in item.findings]})
        )
    return result.model_copy(update={"clauses": cleaned})


async def rate_topic(
    provider: AIProvider,
    document: PseudonymizedDocument,
    topic: ConfirmedTopic,
    *,
    language: OutputLanguage,
    effort: ReasoningEffort | None = None,
) -> TopicRatingOut:
    clauses = set(clause_refs(document))
    max_tokens = topic_max_tokens(topic)

    def make(repair: int) -> AIRequest:
        return RateTopicRequest(
            PromptTemplate.RATE_TOPIC,
            TopicRatingOut,
            max_tokens,
            document=document,
            topic=topic,
            language=language,
            effort=effort,
            repair=repair,
        )

    def check(raw: ModelJson) -> TopicRatingOut:
        return _checked_topic(TopicRatingOut.model_validate(raw), clauses, topic)

    return await _complete(provider, make, check)


async def rate_other(  # noqa: PLR0913
    provider: AIProvider,
    document: PseudonymizedDocument,
    *,
    side: str,
    language: OutputLanguage,
    effort: ReasoningEffort | None = None,
    domain: str | None = None,
    catalog: Catalog | None = None,
) -> OtherRatingOut:
    """``side`` must be a catalog id shape; with a ``catalog`` it must be a side of ``domain``.
    More than 40 clauses is refused. Both raise ``ValueError`` before any call."""
    if not _SIDE_RE.fullmatch(side) or (
        catalog is not None and (domain is None or not catalog.has_side(domain, side))
    ):
        raise ValueError("side is not a catalog side")  # noqa: TRY003
    clauses = clause_refs(document)
    if len(clauses) > MAX_OTHER_CLAUSES:
        raise ValueError("too many clauses for one call")  # noqa: TRY003
    max_tokens = other_max_tokens(len(clauses))

    def make(repair: int) -> AIRequest:
        return RateOtherRequest(
            PromptTemplate.RATE_OTHER,
            OtherRatingOut,
            max_tokens,
            document=document,
            side=side,
            language=language,
            effort=effort,
            repair=repair,
        )

    def check(raw: ModelJson) -> OtherRatingOut:
        return _checked_other(OtherRatingOut.model_validate(raw), clauses)

    return await _complete(provider, make, check)
