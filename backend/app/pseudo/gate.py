"""The type gate and the safety pass (ADR 0008 point 3, ADR 0015 points 4 and 5).

``PseudonymizedDocument``, ``PseudonymizedClause``, ``PseudonymizedText`` and
``ConfirmedTopic`` are the only types the AI layer accepts. They are frozen dataclasses
with slots. Each has an ``InitVar`` sentinel without a default, checked in
``__post_init__``: only code in this module holds the sentinel. Fields are immutable
(strings, tuples of gate objects). ``__copy__``, ``__deepcopy__``, ``__reduce__`` and
``__reduce_ex__`` raise, so ``copy``, ``pickle`` and ``dataclasses.replace`` cannot make
an object. Only ``safety_pass`` creates a ``PseudonymizedDocument``.

``safety_pass`` checks, in order: detector version, input caps, Layer 1 idempotence,
placeholder grammar, the whole detector (every hit inside a placeholder or acknowledged),
and the acknowledged spans. It raises ``SafetyError``; its ``spans`` hold clause ids and
offsets only, never text.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from typing import Final, NoReturn

from app.pseudo.detector import TooManyIdentifiersError, detect
from app.pseudo.hits import HIGH
from app.pseudo.lexicon import DETECTOR_VERSION
from app.pseudo.untrusted import (
    MAX_CLAUSE_CHARS,
    MAX_CLAUSES,
    MAX_DOCUMENT_CHARS,
    UntrustedMaskedDocument,
)
from app.safety.placeholders import PlaceholderError, Range, find_placeholders
from app.segment.model import Clause
from app.textclean import TextCleaner

__all__ = [
    "ConfirmedTopic",
    "PseudonymizedClause",
    "PseudonymizedDocument",
    "PseudonymizedText",
    "SafetyError",
    "safety_pass",
]

_SENTINEL: Final = object()
Span = tuple[str, int, int]


def _refuse(self: object, *args: object) -> NoReturn:
    msg = "gate objects cannot be copied, pickled or rebuilt"
    raise TypeError(msg)


def _check(token: object) -> None:
    if token is not _SENTINEL:
        msg = "gate objects are made by the safety pass only"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class PseudonymizedClause:
    id: str
    text: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token)

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@dataclass(frozen=True, slots=True)
class PseudonymizedDocument:
    label: str
    clauses: tuple[PseudonymizedClause, ...]
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token)

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@dataclass(frozen=True, slots=True)
class PseudonymizedText:
    text: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token)

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@dataclass(frozen=True, slots=True)
class ConfirmedTopic:
    title: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token)

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


class SafetyError(Exception):
    """A check failed. ``code`` is the error code; ``spans`` are ``(clause_id, start, end)``."""

    def __init__(self, code: str, spans: tuple[Span, ...] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.spans = spans


def _detector_clauses(texts: list[str]) -> list[Clause]:
    return [
        Clause(
            id=f"c{index + 1}",
            number=None,
            level=0,
            part_index=0,
            section_kind=None,
            part="body",
            pages=[],
            spans=[(index, 0, len(text))] if text else [],
            heading_span=None,
        )
        for index, text in enumerate(texts)
    ]


def _inside(span: tuple[int, int], ranges: list[Range]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in ranges)


def _leftovers(
    texts: list[str], placeholders: list[list[Range]]
) -> tuple[list[tuple[int, int, int, bool]], set[tuple[int, int, int]]]:
    """Detector hits outside placeholders: ``(clause_index, start, end, high)``."""
    try:
        detection = detect(texts, _detector_clauses(texts))
    except TooManyIdentifiersError:
        raise SafetyError("too_many_identifiers") from None
    found: list[tuple[int, int, int, bool]] = []
    for entity in detection.entities:
        for block, start, end in entity.spans:
            if not _inside((start, end), placeholders[block]):
                found.append((block, start, end, entity.precision == HIGH))
    found.sort()
    return found, {(block, start, end) for block, start, end, _ in found}


def _acknowledged(
    untrusted: UntrustedMaskedDocument, known: set[tuple[int, int, int]]
) -> set[tuple[int, int, int]]:
    """The acknowledged spans as ``(clause_index, start, end)``; every rule of ADR 0015 point 4."""
    position = {clause.id: index for index, clause in enumerate(untrusted.clauses)}
    result = [
        (position[clause_id], start, end)
        for clause_id, start, end in untrusted.acknowledged_unmasked
    ]
    if not set(result) <= known or len(set(result)) != len(result):
        raise SafetyError("invalid_request")
    return set(result)


def safety_pass(
    untrusted: UntrustedMaskedDocument, *, max_clauses: int = MAX_CLAUSES
) -> PseudonymizedDocument:
    """Check a masked document and make the only value the AI layer accepts."""
    if untrusted.detector_version != DETECTOR_VERSION:
        raise SafetyError("detector_version_mismatch")
    texts = [clause.text for clause in untrusted.clauses]
    if (
        len(texts) > max_clauses
        or any(len(text) > MAX_CLAUSE_CHARS for text in texts)
        or sum(len(text) for text in texts) > MAX_DOCUMENT_CHARS
    ):
        raise SafetyError("too_much_text")
    cleaner = TextCleaner()
    if any(cleaner.clean(text) != text for text in texts):
        raise SafetyError("input_not_clean")
    try:
        placeholders = find_placeholders(untrusted.label, texts)
    except PlaceholderError:
        raise SafetyError("invalid_placeholder") from None
    found, known = _leftovers(texts, placeholders)
    acknowledged = _acknowledged(untrusted, known)
    unmasked = tuple(
        (untrusted.clauses[block].id, start, end)
        for block, start, end, high in found
        if high or (block, start, end) not in acknowledged
    )
    if unmasked:
        raise SafetyError("unmasked_identifier", unmasked)
    return PseudonymizedDocument(
        untrusted.label,
        tuple(PseudonymizedClause(c.id, c.text, _SENTINEL) for c in untrusted.clauses),
        _SENTINEL,
    )
