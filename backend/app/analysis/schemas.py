"""Strict output schemas of the two rating calls (ADR 0019 point 2).

A schema is the shape and the caps only. ``app.analysis.rate`` compares an answer with the
request (clause ids, attribute ids, units, value ids). A broken cap fails the whole answer
(no truncation). Explanations are cleaned and checked by code after validation.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tagging.schemas import BadOutputError, ClauseRef

__all__ = [
    "MAX_EXPLANATION",
    "BadOutputError",
    "EvidenceOut",
    "FindingOut",
    "OtherClauseOut",
    "OtherRatingOut",
    "TopicRatingOut",
    "ValueOut",
]

MAX_EXPLANATION: Final = 400
MAX_QUOTE: Final = 1000
MAX_NUMBER: Final = 1e12

Ident = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
Number = Annotated[float, Field(ge=0, le=MAX_NUMBER, allow_inf_nan=False)]
Currency = Literal["UAH", "USD", "EUR", "percent_of_sum", "percent_of_loss"]
DurationUnit = Literal["hours", "days", "working_days", "months", "years"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceOut(_Out):
    clause: ClauseRef
    quote: Annotated[str, Field(min_length=1, max_length=MAX_QUOTE)]


class AmountValue(_Out):
    type: Literal["amount"]
    number: Number
    currency: Currency


class PercentageValue(_Out):
    type: Literal["percentage"]
    number: Number


class DurationValue(_Out):
    type: Literal["duration"]
    number: Number
    unit: DurationUnit


class EnumValue(_Out):
    type: Literal["enum"]
    value: Ident


class CategoriesValue(_Out):
    type: Literal["categories"]
    values: Annotated[list[Ident], Field(max_length=30)]


class TextValue(_Out):
    type: Literal["text"]
    text: Annotated[str, Field(max_length=200)]


class NotStatedValue(_Out):
    type: Literal["not_stated"]


ValueOut = Annotated[
    AmountValue
    | PercentageValue
    | DurationValue
    | EnumValue
    | CategoriesValue
    | TextValue
    | NotStatedValue,
    Field(discriminator="type"),
]


class AttributeOut(_Out):
    attribute: Ident
    value: ValueOut
    evidence: Annotated[list[EvidenceOut], Field(max_length=3)]


class FindingOut(_Out):
    rating: Literal["green", "yellow", "red"]
    attribute: Ident | None
    explanation: Annotated[str, Field(min_length=1, max_length=MAX_EXPLANATION)]
    evidence: Annotated[list[EvidenceOut], Field(min_length=1, max_length=3)]


class TopicRatingOut(_Out):
    attributes: Annotated[list[AttributeOut], Field(max_length=12)]
    findings: Annotated[list[FindingOut], Field(max_length=8)]
    injection_suspected: Annotated[list[EvidenceOut], Field(max_length=3)]


class OtherClauseOut(_Out):
    clause: ClauseRef
    no_issue: bool
    findings: Annotated[list[FindingOut], Field(max_length=2)]

    @model_validator(mode="after")
    def _no_issue_means_no_finding(self) -> Self:
        if self.no_issue == bool(self.findings):
            raise ValueError("no_issue must be true exactly when there is no finding")  # noqa: TRY003
        return self


class OtherRatingOut(_Out):
    clauses: Annotated[list[OtherClauseOut], Field(max_length=40)]
