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

from bisect import bisect_right
from dataclasses import InitVar, dataclass
from itertools import pairwise
from typing import Final, NoReturn, final

from app.pseudo import checksums
from app.pseudo.detector import TooManyIdentifiersError, detect
from app.pseudo.hits import HIGH
from app.pseudo.lexicon import DETECTOR_VERSION
from app.pseudo.untrusted import (
    MAX_CLAUSE_CHARS,
    MAX_CLAUSES,
    MAX_DOCUMENT_CHARS,
    UntrustedMaskedDocument,
)
from app.safety.adjacent import partial_spans
from app.safety.placeholders import Placeholder, PlaceholderError, find_placeholders
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


def _check(token: object, instance: object, cls: type) -> None:
    if token is not _SENTINEL or type(instance) is not cls:
        msg = "gate objects are made by the safety pass only"
        raise TypeError(msg)


def _no_subclass() -> NoReturn:
    msg = "gate types cannot be subclassed"
    raise TypeError(msg)


@final
@dataclass(frozen=True, slots=True)
class PseudonymizedClause:
    id: str
    text: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token, self, PseudonymizedClause)

    def __init_subclass__(cls, **kwargs: object) -> None:
        _no_subclass()

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@final
@dataclass(frozen=True, slots=True)
class PseudonymizedDocument:
    label: str
    clauses: tuple[PseudonymizedClause, ...]
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token, self, PseudonymizedDocument)

    def __init_subclass__(cls, **kwargs: object) -> None:
        _no_subclass()

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@final
@dataclass(frozen=True, slots=True)
class PseudonymizedText:
    text: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token, self, PseudonymizedText)

    def __init_subclass__(cls, **kwargs: object) -> None:
        _no_subclass()

    __copy__ = _refuse
    __deepcopy__ = _refuse
    __reduce__ = _refuse
    __reduce_ex__ = _refuse


@final
@dataclass(frozen=True, slots=True)
class ConfirmedTopic:
    title: str
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        _check(token, self, ConfirmedTopic)

    def __init_subclass__(cls, **kwargs: object) -> None:
        _no_subclass()

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


def _inside(span: tuple[int, int], ranges: list[Placeholder]) -> bool:
    """``span`` lies in one of the sorted, non-overlapping placeholder ``ranges``."""
    index = bisect_right(ranges, (span[0], MAX_CLAUSE_CHARS + 1, "~")) - 1
    return index >= 0 and ranges[index][0] <= span[0] and span[1] <= ranges[index][1]


def _checksummed(cls: str, value: str) -> bool:
    """A TAX_ID or ACCOUNT value with a valid check digit: never acknowledged."""
    compact = "".join(char for char in value if char.isalnum()).upper()
    if cls == "TAX_ID":
        return any(
            check(compact)
            for check in (
                checksums.edrpou_valid,
                checksums.rnokpp_valid,
                checksums.inn10_valid,
                checksums.inn12_valid,
                checksums.ogrn_valid,
                checksums.ogrnip_valid,
            )
        )
    if cls == "ACCOUNT":
        return checksums.iban_valid(compact) or (
            compact.isdigit() and checksums.luhn_valid(compact)
        )
    return False


def _leftovers(
    texts: list[str], placeholders: list[list[Placeholder]]
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
                high = entity.precision == HIGH or _checksummed(entity.cls, texts[block][start:end])
                found.append((block, start, end, high))
    found.sort()
    return found, {(block, start, end) for block, start, end, _ in found}


def _acknowledged(
    untrusted: UntrustedMaskedDocument, known: set[tuple[int, int, int]]
) -> set[tuple[int, int, int]]:
    """The acknowledged spans as ``(clause_index, start, end)``; every rule of ADR 0015 point 4."""
    position = {clause.id: index for index, clause in enumerate(untrusted.clauses)}
    result: list[tuple[int, int, int]] = []
    for clause_id, start, end in untrusted.acknowledged_unmasked:
        index = position.get(clause_id)
        if index is None or start >= end or end > len(untrusted.clauses[index].text):
            raise SafetyError("invalid_request")
        result.append((index, start, end))
    # Sorted by (clause position, start), no overlap, no duplicate.
    for before, after in pairwise(result):
        if (after[0], after[1]) < (before[0], before[2]):
            raise SafetyError("invalid_request")
    if not set(result) <= known:
        raise SafetyError("invalid_request")
    return set(result)


def safety_pass(
    untrusted: UntrustedMaskedDocument, *, max_clauses: int = MAX_CLAUSES
) -> PseudonymizedDocument:
    """Check a masked document and make the only value the AI layer accepts."""
    if untrusted.detector_version != DETECTOR_VERSION:
        raise SafetyError("detector_version_mismatch")
    position = {clause.id for clause in untrusted.clauses}
    if any(clause_id not in position for clause_id, _, _ in untrusted.acknowledged_unmasked):
        raise SafetyError("invalid_request")
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
    leftover = {
        (block, start, end)
        for block, start, end, high in found
        if high or (block, start, end) not in acknowledged
    } | partial_spans(texts, placeholders)
    unmasked = tuple(
        (untrusted.clauses[block].id, start, end) for block, start, end in sorted(leftover)
    )
    if unmasked:
        raise SafetyError("unmasked_identifier", unmasked)
    return PseudonymizedDocument(
        untrusted.label,
        tuple(PseudonymizedClause(c.id, c.text, _SENTINEL) for c in untrusted.clauses),
        _SENTINEL,
    )
