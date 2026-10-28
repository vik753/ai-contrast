"""Parent side of segmentation: run the sandbox child and validate its reply (ADR 0014).

The parent never parses the request body: the raw bytes go to the child (worker kind
``segment``). The reply is validated with the strict models; anything outside the
contract is ``segment_failed``. Errors map like extraction: ``extraction_timeout`` to
``segment_timeout``, every other failure to ``segment_failed``. One log line holds the
outcome code and the duration only.
"""

from __future__ import annotations

import logging
import time
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.extraction.model import EXTRACTION_TIMEOUT, ExtractionError
from app.extraction.sandbox import SandboxLimits, run_child
from app.segment.model import (
    SEGMENT_FAILED,
    SEGMENT_TIMEOUT,
    TOO_MUCH_TEXT,
    SegmentChildError,
    SegmentResult,
)
from app.segment.segmenter import SegmentError, SegmentLimits

logger = logging.getLogger("ai_contrast.segment")


class _ChildReply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    result: SegmentResult | None = None
    error: SegmentChildError | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.result is None) == (self.error is None):
            msg = "exactly one of result and error"
            raise ValueError(msg)
        return self


def _check(result: SegmentResult, limits: SandboxLimits, segment_limits: SegmentLimits) -> None:
    """The caps and the span ranges again, in the parent: every cap fails closed."""
    if len(result.blocks) > limits.max_blocks or (
        sum(len(block.text) for block in result.blocks) > limits.max_text_chars
    ):
        raise SegmentError(TOO_MUCH_TEXT)
    if len(result.clauses) > segment_limits.max_clauses:
        raise SegmentError(SEGMENT_FAILED)
    sizes = [len(block.text) for block in result.blocks]
    for clause in result.clauses:
        spans = list(clause.spans)
        if clause.heading_span is not None:
            spans.append(clause.heading_span)
        for index, start, end in spans:
            if index >= len(sizes) or not start < end <= sizes[index]:
                raise SegmentError(SEGMENT_FAILED)


async def _run(
    body: bytes, limits: SandboxLimits, segment_limits: SegmentLimits, hook: str | None
) -> SegmentResult:
    header: dict[str, object] = {
        "kind": "segment",
        "size": len(body),
        "max_text_chars": limits.max_text_chars,
        "max_blocks": limits.max_blocks,
        "pdf_max_pages": limits.pdf_max_pages,
        "segment_max_clauses": segment_limits.max_clauses,
        "segment_max_clause_chars": segment_limits.max_clause_chars,
    }
    try:
        output = await run_child(header, body, limits, hook)
    except ExtractionError as error:
        code = SEGMENT_TIMEOUT if error.code == EXTRACTION_TIMEOUT else SEGMENT_FAILED
        raise SegmentError(code) from None
    try:
        reply = _ChildReply.model_validate_json(output)
    except ValidationError:
        # `from None`: a validation error may quote the child output.
        raise SegmentError(SEGMENT_FAILED) from None
    if reply.error is not None:
        raise SegmentError(reply.error)
    if reply.result is None:  # pragma: no cover - excluded by the validator
        raise SegmentError(SEGMENT_FAILED)
    _check(reply.result, limits, segment_limits)
    return reply.result


async def run_segmentation(
    body: bytes,
    *,
    limits: SandboxLimits,
    segment_limits: SegmentLimits,
    hook: str | None = None,
) -> SegmentResult:
    """Segment the JSON request ``body`` in a new child process.

    Raises ``SegmentError`` with a code. ``hook`` is for tests only (see the sandbox
    module); the HTTP handler never passes it.
    """
    start = time.monotonic()
    outcome = SEGMENT_FAILED
    try:
        result = await _run(body, limits, segment_limits, hook)
        outcome = "ok"
    except SegmentError as error:
        outcome = error.code
        raise
    finally:
        logger.info(
            "segmentation outcome=%s duration_ms=%d", outcome, (time.monotonic() - start) * 1000
        )
    return result
