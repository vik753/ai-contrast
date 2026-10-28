"""The segmentation work inside the sandbox child (ADR 0014 point 2, ADR 0011).

``run`` gets the raw request bytes. The parent never parses them. Here the bytes are
validated by strict Pydantic ``model_validate_json`` (extra fields forbidden; its
parser is not recursive on nesting, it stops at a fixed depth and fails). The parser
keeps the last value of a repeated key, so a second pass rejects duplicate keys; that
pass runs only on input that already has the fixed, shallow shape, so the stdlib
parser cannot recurse deeply. Lone surrogates are rejected by the parser (they fail
closed as ``invalid_request``); other invisible characters are removed by the cleaning
in ``segment`` and reported in ``removed``.

The reply is ``{"result": ...}`` or ``{"error": "<code>"}``.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.extraction.model import Block
from app.pseudo.detector import TooManyIdentifiersError, detect
from app.pseudo.lexicon import DETECTOR_VERSION
from app.segment.model import (
    INVALID_REQUEST,
    TOO_MANY_IDENTIFIERS,
    TOO_MUCH_TEXT,
    Entity,
    RequisitesClause,
    RequisitesLine,
    SegmentCore,
    SegmentRequest,
    SegmentResult,
    SegmentWarning,
)
from app.segment.segmenter import SegmentError, SegmentLimits, segment


def _error(code: str) -> bytes:
    return json.dumps({"error": code}).encode()


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def _detected(core: SegmentCore) -> SegmentResult:
    """Run the detector on the cleaned blocks (ADR 0015 point 1)."""
    detection = detect([block.text for block in core.blocks], core.clauses)
    blocks = [
        Block(text=text, part=block.part, page=block.page)
        for text, block in zip(detection.texts, core.blocks, strict=True)
    ]
    warnings = [
        *core.warnings,
        *(SegmentWarning(code=code, clause=clause) for code, clause in detection.warnings),
    ]
    return SegmentResult(
        clauses=core.clauses,
        blocks=blocks,
        removed=core.removed,
        warnings=warnings,
        detector_version=DETECTOR_VERSION,
        entities=[
            Entity.model_validate(
                {
                    "id": entity.id,
                    "class": entity.cls,
                    "precision": entity.precision,
                    "spans": entity.spans,
                }
            )
            for entity in detection.entities
        ],
        requisites=[
            RequisitesClause(
                clause=clause,
                lines=[RequisitesLine(span=span, action=action) for span, action in lines],
            )
            for clause, lines in detection.requisites
        ],
        neutralized=detection.neutralized,
    )


def run(  # noqa: PLR0913 - the caps come from the parent header, one value each
    data: bytes,
    *,
    max_text_chars: int,
    max_blocks: int,
    max_pages: int,
    max_clauses: int,
    max_clause_chars: int,
) -> bytes:
    try:
        request = SegmentRequest.model_validate_json(data)
        json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (ValidationError, ValueError):
        return _error(INVALID_REQUEST)
    if any(block.page is not None and block.page > max_pages for block in request.blocks):
        return _error(INVALID_REQUEST)
    if len(request.blocks) > max_blocks or (
        sum(len(block.text) for block in request.blocks) > max_text_chars
    ):
        return _error(TOO_MUCH_TEXT)
    try:
        core = segment(
            request.blocks,
            limits=SegmentLimits(max_clauses=max_clauses, max_clause_chars=max_clause_chars),
        )
        result = _detected(core)
    except SegmentError as error:
        return _error(error.code)
    except TooManyIdentifiersError:
        return _error(TOO_MANY_IDENTIFIERS)
    return b'{"result":' + result.model_dump_json(by_alias=True).encode() + b"}"
