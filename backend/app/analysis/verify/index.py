"""The document index: marker and reference positions of every clause, built once.

Pure and frozen. There is no module-level cache: the caller builds one index per document
and passes it to ``apply_green_rules`` and ``verify_value`` (they build one when it is
missing). Offsets point into the original clause texts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.analysis.verify.lexicon import LANGS, LEXICON
from app.analysis.verify.model import Clause, Span
from app.analysis.verify.numbers import states_scale
from app.analysis.verify.quote import expand_quote
from app.analysis.verify.refs import NumberTable, Reference, covers, find_references_in
from app.analysis.verify.text import Markers, Source, normalize

__all__ = ["ClauseInfo", "DocumentIndex", "InRef", "build_document_index"]

EXCEPTIONS: Final = Markers((lang, e) for lang in LANGS for e in LEXICON.exception_markers[lang])
OVERRIDES: Final = Markers(
    (lang, e) for lang in LANGS for e in LEXICON.global_override_markers[lang]
)
UNRESOLVED: Final = Markers(
    (lang, e)
    for lang in LANGS
    for e in (*LEXICON.relative_references[lang], *LEXICON.ref_self[lang])
)


@dataclass(frozen=True, slots=True)
class ClauseInfo:
    """What the rules need to know about one clause."""

    exception: Span | None  # sentence of the first marker; the whole clause for a heading hit
    override: Span | None
    unresolved: bool
    refs: tuple[Reference, ...]  # in the text
    heading_refs: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class InRef:
    """A reference found in clause ``clause`` (offsets in its text; ``heading``: in its heading)."""

    clause: str
    ref: Reference
    heading: bool


@dataclass(frozen=True, slots=True)
class DocumentIndex:
    by_id: Mapping[str, Clause]
    info: Mapping[str, ClauseInfo]
    numbers: NumberTable
    overrides: tuple[Span, ...]
    inbound: Mapping[str, tuple[InRef, ...]]  # exact referenced number -> references
    ranges: tuple[InRef, ...]
    scaled: bool  # some clause states a scale ("amounts in thousands")

    def inbound_to(self, number: str) -> list[InRef]:
        """References that name ``number``: exact, its parents ("4" for "4.1"), and ranges."""
        found: list[InRef] = []
        parts = number.split(".")
        for k in range(1, len(parts) + 1):
            found.extend(self.inbound.get(".".join(parts[:k]), ()))
        found.extend(r for r in self.ranges if covers(r.ref, number))
        return found


def _marker(
    markers: Markers,
    clause: Clause,
    text: tuple[str, Source | None],
    head: tuple[str, Source | None],
) -> Span | None:
    hit = markers.first_in(*text)
    if hit is not None:
        a, b = expand_quote(clause.text, *hit)
        return clause.id, a, b
    if clause.heading and markers.first_in(*head) is not None:
        return clause.id, 0, len(clause.text)
    return None


def build_document_index(clauses: Sequence[Clause]) -> DocumentIndex:
    """Scan every clause once for markers and references."""
    by_id: dict[str, Clause] = {}
    for clause in clauses:
        by_id.setdefault(clause.id, clause)
    numbers = NumberTable(by_id.values())
    known = numbers.by_number.keys()
    info: dict[str, ClauseInfo] = {}
    overrides: list[Span] = []
    inbound: dict[str, list[InRef]] = {}
    ranges: list[InRef] = []
    for cid, clause in by_id.items():
        text = normalize(clause.text) if clause.text else ("", None)
        head = normalize(clause.heading) if clause.heading else ("", None)
        refs = tuple(find_references_in(*text, known))
        heading_refs = tuple(find_references_in(*head, known))
        override = _marker(OVERRIDES, clause, text, head)
        info[cid] = ClauseInfo(
            exception=_marker(EXCEPTIONS, clause, text, head),
            override=override,
            unresolved=(
                UNRESOLVED.first_in(*text) is not None or UNRESOLVED.first_in(*head) is not None
            ),
            refs=refs,
            heading_refs=heading_refs,
        )
        if override is not None:
            overrides.append(override)
        for items, is_heading in ((refs, False), (heading_refs, True)):
            for ref in items:
                entry = InRef(cid, ref, is_heading)
                if ref.high is None:
                    inbound.setdefault(ref.low, []).append(entry)
                else:
                    ranges.append(entry)
    return DocumentIndex(
        by_id=by_id,
        info=info,
        numbers=numbers,
        overrides=tuple(overrides),
        inbound={k: tuple(v) for k, v in inbound.items()},
        ranges=tuple(ranges),
        scaled=any(states_scale(c.text) or states_scale(c.heading) for c in by_id.values()),
    )
