"""Public types of the verification library (ADR 0019 points 3 and 4). Frozen, no text out."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

Span = tuple[str, int, int]  # (clause id, start, end) into Clause.text


class Rating(StrEnum):
    green = "green"
    yellow = "yellow"
    red = "red"


class Reason(StrEnum):
    quote_too_short = "quote_too_short"
    suspicious_span = "suspicious_span"
    check_exceptions = "check_exceptions"
    global_override = "global_override"
    too_many_references = "too_many_references"
    unresolved_reference = "unresolved_reference"
    number_mismatch = "number_mismatch"
    document_flags = "document_flags"
    other_not_green = "other_not_green"
    unverified = "unverified"
    incomplete = "incomplete"


class DocFlag(StrEnum):
    not_read_material = "not_read_material"
    hidden_text_removed = "hidden_text_removed"


class ValueStatus(StrEnum):
    verified = "verified"
    not_confirmed = "not_confirmed"


class TopicState(StrEnum):
    ok = "ok"
    model_tags_dropped = "model_tags_dropped"
    not_analyzed = "not_analyzed"


@dataclass(frozen=True, slots=True)
class Clause:
    id: str
    text: str
    heading: str = ""
    number: str | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    clause: str
    quote: str


@dataclass(frozen=True, slots=True)
class NumericValue:
    number: Decimal
    unit: str | None


@dataclass(frozen=True, slots=True)
class Finding:
    rating: Rating
    evidence: tuple[Evidence, ...]
    topic: str | None
    attribute: str | None = None
    value: NumericValue | None = None


@dataclass(frozen=True, slots=True)
class DocumentContext:
    clauses: tuple[Clause, ...]
    topic_clauses: Mapping[str, frozenset[str]] = field(default_factory=dict)
    flags: frozenset[DocFlag] = frozenset()
    unprovided_reference_clauses: frozenset[str] = frozenset()
    layer2_spans: tuple[Span, ...] = ()
    layer2_heuristic_clauses: frozenset[str] = frozenset()
    injection: tuple[Evidence, ...] = ()
    incomplete: bool = False


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    ok: bool
    spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RatedFinding:
    rating: Rating
    reasons: tuple[Reason, ...]
    verified_spans: tuple[Span, ...]
    attached: tuple[Span, ...]
    dropped_quotes: int
    unverified: bool


@dataclass(frozen=True, slots=True)
class ClosureEntry:
    added: tuple[str, ...]
    needed: int
    too_many: bool


@dataclass(frozen=True, slots=True)
class ValueIn:
    attribute: str
    evidence: tuple[Evidence, ...]
    topic: str | None = None
    number: NumericValue | None = None


@dataclass(frozen=True, slots=True)
class ValueOut:
    status: ValueStatus
    reasons: tuple[Reason, ...]


@dataclass(frozen=True, slots=True)
class TaggingState:
    complete: bool
    signed: bool


@dataclass(frozen=True, slots=True)
class TopicInfo:
    id: str
    clause_count: int
    state: TopicState
    essential: bool


@dataclass(frozen=True, slots=True)
class MissingTopicFinding:
    topic: str
    rating: Rating


@dataclass(frozen=True, slots=True)
class Completeness:
    incomplete: bool
    unrated_other: int
    greens_allowed: bool
