"""Models of ``POST /api/segment`` (ADR 0014; docs/agent/TASKS.md, S5-T1).

Strict and frozen: the parent validates every reply of the sandbox child with them, so
anything outside the contract fails closed with ``segment_failed``.

A ``Span`` is ``(block_index, start, end)`` into the cleaned ``blocks`` of the reply.
The clause text is the span texts joined with ``\\n``; the reply holds no copy of it.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

from app.extraction.model import Block, Code, Part, Removed

Span = tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt]
ClausePart = Literal[
    "body", "footnote", "endnote", "header", "footer", "textbox", "running", "preamble"
]

# Codes of the segmentation endpoint.
SEGMENT_FAILED: Final = "segment_failed"
SEGMENT_TIMEOUT: Final = "segment_timeout"
INVALID_REQUEST: Final = "invalid_request"
TOO_MUCH_TEXT: Final = "too_much_text"
NO_TEXT_EXTRACTED: Final = "no_text_extracted"
TOO_MANY_CLAUSES: Final = "too_many_clauses"
CLAUSE_TOO_LONG: Final = "clause_too_long"
TOO_MANY_IDENTIFIERS: Final = "too_many_identifiers"

# Codes that the child may report. The parent's own codes (timeout, failure) are not
# in this list: a child cannot claim them.
SegmentChildError = Literal[
    "invalid_request",
    "too_much_text",
    "no_text_extracted",
    "too_many_clauses",
    "clause_too_long",
    "too_many_identifiers",
]
LineAction = Literal["drop", "keep"]
EntityClass = Literal[
    "ORG",
    "PERSON",
    "TAX_ID",
    "ACCOUNT",
    "ADDRESS",
    "PHONE",
    "EMAIL",
    "URL",
    "PERSONAL_DOC",
    "DOC_NO",
    "VEHICLE",
    "SIGNATURE",
    "HEALTH",
]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class InputBlock(_Strict):
    """One text block of the request (the ``/api/extract`` block shape)."""

    text: str
    part: Part
    page: PositiveInt | None


class SegmentRequest(_Strict):
    blocks: list[InputBlock]


class Clause(_Strict):
    id: Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,6}$")]
    number: str | None
    level: NonNegativeInt
    part_index: NonNegativeInt
    section_kind: Literal["requisites"] | None
    part: ClausePart
    pages: list[PositiveInt]
    spans: list[Span]
    heading_span: Span | None


class SegmentWarning(_Strict):
    code: Code
    clause: str | None


class SegmentCore(_Strict):
    """The segmentation part of the reply (what ``segment`` returns)."""

    clauses: list[Clause]
    blocks: list[Block]
    removed: list[Removed]
    warnings: list[SegmentWarning]


class Entity(_Strict):
    """One identifier in the document: all its occurrences, no value string (ADR 0015)."""

    id: Annotated[str, Field(pattern=r"^e[1-9][0-9]{0,4}$")]
    cls: EntityClass = Field(alias="class")
    precision: Literal["high", "normal"]
    spans: list[Span]


class RequisitesLine(_Strict):
    span: Span
    action: LineAction


class RequisitesClause(_Strict):
    clause: Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,6}$")]
    lines: list[RequisitesLine]


class SegmentResult(SegmentCore):
    detector_version: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,64}$")]
    entities: list[Entity]
    requisites: list[RequisitesClause]
    neutralized: list[Span]
