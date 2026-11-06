"""Green rules and verified values (ADR 0019 point 3). Pure; offsets and codes out, never text."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from app.analysis.verify.lexicon import LANGS, LEXICON
from app.analysis.verify.model import (
    Clause,
    DocumentContext,
    Evidence,
    Finding,
    NumericValue,
    RatedFinding,
    Rating,
    Reason,
    Span,
    ValueIn,
    ValueOut,
    ValueStatus,
)
from app.analysis.verify.numbers import number_values
from app.analysis.verify.quote import expand_quote, verify_quote
from app.analysis.verify.refs import covers, find_references, reference_closure
from app.analysis.verify.text import Markers

__all__ = ["apply_green_rules", "verify_value"]

MIN_QUOTE_CHARS: Final = 25
MAX_ATTACHED: Final = 20
_EXCEPTIONS: Final = Markers((lang, e) for lang in LANGS for e in LEXICON.exception_markers[lang])
_OVERRIDES: Final = Markers(
    (lang, e) for lang in LANGS for e in LEXICON.global_override_markers[lang]
)
_UNRESOLVED: Final = Markers(
    (lang, e) for lang in LANGS for e in (*LEXICON.ref_relative[lang], *LEXICON.ref_external[lang])
)
_VALUE_IGNORED: Final = frozenset({Reason.quote_too_short, Reason.other_not_green})


@dataclass(slots=True)
class _Eval:
    reasons: set[Reason] = field(default_factory=set)
    attached: list[Span] = field(default_factory=list)
    verified: list[Span] = field(default_factory=list)
    dropped: int = 0

    def attach(self, span: Span) -> None:
        if span not in self.attached and len(self.attached) < MAX_ATTACHED:
            self.attached.append(span)


def _marker_span(markers: Markers, clause: Clause) -> Span | None:
    """The sentence of the first marker in the clause text, or the whole clause when only
    the heading holds one."""
    hit = markers.first(clause.text)
    if hit is not None:
        a, b = expand_quote(clause.text, *hit)
        return clause.id, a, b
    if clause.heading and markers.first(clause.heading) is not None:
        return clause.id, 0, len(clause.text)
    return None


def _overlaps(merged: list[tuple[int, int]], starts: list[int], a: int, b: int) -> bool:
    k = bisect_left(starts, b) - 1
    return k >= 0 and merged[k][1] > a


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _evaluate(  # noqa: PLR0912
    ctx: DocumentContext,
    evidence: Sequence[Evidence],
    topic: str | None,
    number: NumericValue | None,
) -> _Eval:
    ev = _Eval()
    by_id: dict[str, Clause] = {}
    for clause in ctx.clauses:
        by_id.setdefault(clause.id, clause)
    quoted: dict[str, Clause] = {}  # clauses named by the evidence (valid ids only)
    raw: list[Span] = []
    seen: set[Span] = set()
    for item in evidence:
        found = by_id.get(item.clause)
        if found is None:
            ev.dropped += 1
            continue
        clause = found
        quoted.setdefault(clause.id, clause)
        check = verify_quote(clause, item.quote)
        if not check.ok:
            ev.dropped += 1
            continue
        prev = (-1, -1)
        for a, b in check.spans:
            raw.append((clause.id, a, b))
            if prev[0] <= a and b <= prev[1]:
                continue  # inside the sentence already expanded
            prev = expand_quote(clause.text, a, b)
            span = (clause.id, *prev)
            if span not in seen:
                seen.add(span)
                ev.verified.append(span)
    reasons = ev.reasons
    if not ev.verified:
        reasons.add(Reason.unverified)
    if topic is None:
        reasons.add(Reason.other_not_green)
    if ctx.incomplete:
        reasons.add(Reason.incomplete)
    if ctx.flags or ctx.unprovided_reference_clauses & quoted.keys():
        reasons.add(Reason.document_flags)
    if any(s[2] - s[1] < MIN_QUOTE_CHARS for s in ev.verified):
        reasons.add(Reason.quote_too_short)
    _suspicious(ctx, quoted, raw, ev)
    _exceptions(ctx, by_id, quoted, topic, ev)
    for each in ctx.clauses:
        override = _marker_span(_OVERRIDES, each)
        if override is not None:
            reasons.add(Reason.global_override)
            ev.attach(override)
    if any(
        _UNRESOLVED.first(c.text) is not None
        or (c.heading and _UNRESOLVED.first(c.heading) is not None)
        for c in quoted.values()
    ):
        reasons.add(Reason.unresolved_reference)
    if any(e.too_many for e in reference_closure(ctx.clauses, quoted).values()):
        reasons.add(Reason.too_many_references)
    if number is not None and ev.verified and not _number_ok(by_id, ev.verified, number):
        reasons.add(Reason.number_mismatch)
    return ev


def _suspicious(
    ctx: DocumentContext, quoted: dict[str, Clause], raw: list[Span], ev: _Eval
) -> None:
    injected = {item.clause for item in ctx.injection}
    if any(cid in injected or cid in ctx.layer2_heuristic_clauses for cid in quoted):
        ev.reasons.add(Reason.suspicious_span)
        return
    per_clause: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e in ctx.layer2_spans:
        if cid in quoted:
            per_clause[cid].append((s, e))
    merged = {cid: _merge(spans) for cid, spans in per_clause.items()}
    starts = {cid: [s for s, _ in spans] for cid, spans in merged.items()}
    for cid, a, b in raw:
        if cid in merged and _overlaps(merged[cid], starts[cid], a, b):
            ev.reasons.add(Reason.suspicious_span)
            return


def _exceptions(
    ctx: DocumentContext,
    by_id: dict[str, Clause],
    quoted: dict[str, Clause],
    topic: str | None,
    ev: _Eval,
) -> None:
    for clause in quoted.values():
        span = _marker_span(_EXCEPTIONS, clause)
        if span is not None:
            ev.reasons.add(Reason.check_exceptions)
            ev.attach(span)
    if topic is not None:
        for cid in sorted(ctx.topic_clauses.get(topic, ())):
            other = by_id.get(cid)
            if other is None or cid in quoted:
                continue
            span = _marker_span(_EXCEPTIONS, other)
            if span is not None:
                ev.reasons.add(Reason.check_exceptions)
                ev.attach(span)
    numbers = [c.number for c in quoted.values() if c.number is not None]
    if not numbers:
        return
    known = {c.number for c in ctx.clauses if c.number is not None}
    for other in ctx.clauses:
        if other.id in quoted:
            continue
        for ref in find_references(other.text, known):
            if any(covers(ref, n) for n in numbers):
                s, e = expand_quote(other.text, ref.start, ref.end)
                ev.reasons.add(Reason.check_exceptions)
                ev.attach((other.id, s, e))
                break


def _number_ok(by_id: dict[str, Clause], spans: list[Span], number: NumericValue) -> bool:
    found: set[object] = set()
    for cid, a, b in spans:
        found |= number_values(by_id[cid].text[a:b], number.unit)
    return found == {number.number}


def _ordered(reasons: set[Reason]) -> tuple[Reason, ...]:
    return tuple(r for r in Reason if r in reasons)


def apply_green_rules(ctx: DocumentContext, finding: Finding) -> RatedFinding:
    """Cap a green to yellow when a rule fails. Yellow and red never change."""
    ev = _evaluate(ctx, finding.evidence, finding.topic, finding.value)
    rating = finding.rating
    reasons: tuple[Reason, ...] = ()
    attached: tuple[Span, ...] = ()
    if rating is Rating.green and ev.reasons:
        rating = Rating.yellow
        reasons = _ordered(ev.reasons)
        attached = tuple(ev.attached)
    return RatedFinding(
        rating=rating,
        reasons=reasons,
        verified_spans=tuple(ev.verified),
        attached=attached,
        dropped_quotes=ev.dropped,
        unverified=not ev.verified,
    )


def verify_value(ctx: DocumentContext, value: ValueIn) -> ValueOut:
    """``verified`` only with a verified quote, a passing number check and no cap."""
    ev = _evaluate(ctx, value.evidence, value.topic, value.number)
    reasons = ev.reasons - _VALUE_IGNORED
    return ValueOut(
        ValueStatus.not_confirmed if reasons else ValueStatus.verified, _ordered(reasons)
    )
