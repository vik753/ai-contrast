"""Parent side of the safety check: run the sandbox child and validate its reply.

The parent never parses the request body. The reply is validated with strict models;
anything outside the contract is ``safety_failed``. One log line holds the outcome code,
the duration and a span count, never an id, an offset or a value.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, TypeAdapter, ValidationError

from app.extraction.model import EXTRACTION_TIMEOUT, ExtractionError
from app.extraction.sandbox import SandboxLimits, run_child
from app.pseudo.hits import MAX_SPANS

logger = logging.getLogger("ai_contrast.safety")

SAFETY_FAILED: Final = "safety_failed"
SAFETY_TIMEOUT: Final = "safety_timeout"
UNMASKED: Final = "unmasked_identifier"
MISMATCH: Final = "detector_version_mismatch"
ChildCode = Literal[
    "detector_version_mismatch",
    "input_not_clean",
    "invalid_placeholder",
    "unmasked_identifier",
    "invalid_request",
    "too_much_text",
    "too_many_identifiers",
]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class SafetyOk(_Strict):
    ok: Literal[True]
    detector_version: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,64}$")]
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SafetyFailure(_Strict):
    error: ChildCode
    spans: Annotated[
        list[
            tuple[
                Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,3}$")], NonNegativeInt, NonNegativeInt
            ]
        ],
        Field(max_length=MAX_SPANS),
    ] = Field(default_factory=list)


class SafetyRunError(Exception):
    """The check failed with ``code``; ``spans`` are offsets only."""

    def __init__(self, code: str, spans: list[tuple[str, int, int]] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.spans = spans or []


_REPLY: Final = TypeAdapter(SafetyOk | SafetyFailure)


async def _run(body: bytes, limits: SandboxLimits, max_clauses: int, hook: str | None) -> SafetyOk:
    header: dict[str, object] = {
        "kind": "safety",
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
    if isinstance(reply, SafetyFailure):
        raise SafetyRunError(reply.error, list(reply.spans))
    return reply


async def run_safety_check(
    body: bytes, *, limits: SandboxLimits, max_clauses: int, hook: str | None = None
) -> SafetyOk:
    """Check the JSON request ``body`` in a new child process. Raises ``SafetyRunError``."""
    start = time.monotonic()
    outcome = SAFETY_FAILED
    count = 0
    try:
        result = await _run(body, limits, max_clauses, hook)
        outcome = "ok"
    except SafetyRunError as error:
        outcome = error.code
        count = len(error.spans)
        raise
    finally:
        logger.info(
            "safety outcome=%s unmasked=%d duration_ms=%d",
            outcome,
            count,
            (time.monotonic() - start) * 1000,
        )
    return result
