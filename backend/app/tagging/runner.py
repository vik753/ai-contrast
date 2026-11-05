"""Parent side of the tagging step: run the sandbox child and validate its reply.

The reply is validated with strict models; anything outside the contract is ``safety_failed``.
One log line holds the outcome code, the duration and counts, never an id, an offset or a value.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, TypeAdapter, ValidationError

from app.extraction.model import EXTRACTION_TIMEOUT, ExtractionError
from app.extraction.sandbox import SandboxLimits, run_child
from app.pseudo.hits import MAX_SPANS
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.runner import SAFETY_FAILED, SAFETY_TIMEOUT, SafetyRunError
from app.tagging.child import ChildRequest, ChildTopic

__all__ = ["TagChildOk", "run_tag_child"]

logger = logging.getLogger("ai_contrast.tagging")

KEYWORD_BUDGET_EXCEEDED: Final = "keyword_budget_exceeded"
ClauseRef = Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,3}$")]
Span = tuple[NonNegativeInt, NonNegativeInt, Literal["heuristic", "high"]]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Layer2Hits(_Strict):
    text: list[Span]
    heading: list[Span]


class TagChildOk(_Strict):
    ok: Literal[True]
    detector_version: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,64}$")]
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    keyword: dict[ClauseRef, list[str]]
    layer2: dict[ClauseRef, Layer2Hits]

    def keyword_sets(self) -> dict[str, set[str]]:
        return {clause_id: set(topic_ids) for clause_id, topic_ids in self.keyword.items()}


class TagChildFailure(_Strict):
    error: Literal[
        "detector_version_mismatch",
        "input_not_clean",
        "invalid_placeholder",
        "unmasked_identifier",
        "invalid_request",
        "too_much_text",
        "too_many_identifiers",
        "keyword_budget_exceeded",
    ]
    spans: Annotated[
        list[tuple[ClauseRef, NonNegativeInt, NonNegativeInt]], Field(max_length=MAX_SPANS)
    ] = Field(default_factory=list)


_REPLY: Final = TypeAdapter(TagChildOk | TagChildFailure)


async def _run(
    request: ChildRequest, limits: SandboxLimits, max_clauses: int, hook: str | None
) -> TagChildOk:
    body = request.model_dump_json().encode("utf-8")
    header: dict[str, object] = {
        "kind": "tag",
        "size": len(body),
        "max_text_chars": limits.max_text_chars,
        "max_blocks": limits.max_blocks,
        "safety_max_clauses": max_clauses,
    }
    try:
        output = await run_child(header, body, limits, hook)
    except ExtractionError as error:
        raise SafetyRunError(
            SAFETY_TIMEOUT if error.code == EXTRACTION_TIMEOUT else SAFETY_FAILED
        ) from None
    try:
        reply = _REPLY.validate_json(output)
    except ValidationError:
        raise SafetyRunError(SAFETY_FAILED) from None
    if isinstance(reply, TagChildFailure):
        raise SafetyRunError(reply.error, list(reply.spans))
    clause_ids = {clause.id for clause in request.document.clauses}
    topic_ids = {topic.topic_id for topic in request.topics}
    if set(reply.keyword) != clause_ids or not set(reply.layer2) <= clause_ids:
        raise SafetyRunError(SAFETY_FAILED)
    if any(not set(found) <= topic_ids for found in reply.keyword.values()):
        raise SafetyRunError(SAFETY_FAILED)
    return reply


async def run_tag_child(  # noqa: PLR0913
    document: UntrustedMaskedDocument,
    topics: Sequence[ChildTopic],
    *,
    keyword_budget: int,
    limits: SandboxLimits,
    max_clauses: int,
    hook: str | None = None,
) -> TagChildOk:
    """Safety pass, keyword tags and Layer 2 in a new child process.

    Raises ``SafetyRunError`` (its code is a safety code or ``keyword_budget_exceeded``)."""
    request = ChildRequest(document=document, topics=list(topics), keyword_budget=keyword_budget)
    start = time.monotonic()
    outcome = SAFETY_FAILED
    count = 0
    try:
        result = await _run(request, limits, max_clauses, hook)
        outcome = "ok"
        count = len(result.layer2)
    except SafetyRunError as error:
        outcome = error.code
        count = len(error.spans)
        raise
    finally:
        logger.info(
            "tag step outcome=%s count=%d duration_ms=%d",
            outcome,
            count,
            (time.monotonic() - start) * 1000,
        )
    return result
