"""Green rules and verified values (ADR 0019 point 3). Pure; offsets and codes out, never text."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.analysis.verify.index import DocumentIndex, InRef, build_document_index
from app.analysis.verify.model import (
    Clause,
    ClosureEntry,
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

__all__ = ["apply_green_rules", "verify_value"]

MIN_QUOTE_CHARS: Final = 25
MAX_ATTACHED: Final = 20
MAX_REFS: Final = 5
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


def _quotes(
    index: DocumentIndex, evidence: Sequence[Evidence], ev: _Eval
) -> tuple[dict[str, Clause], list[Span]]:
    """Verify the quotes. Returns the clauses named by the evidence (valid ids only) and the
    raw quote spans; fills the expanded spans, one per sentence."""
    quoted: dict[str, Clause] = {}
    raw: list[Span] = []
    seen: set[Span] = set()
    for item in evidence:
        clause = index.by_id.get(item.clause)
        if clause is None:
            ev.dropped += 1
            continue
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
    return quoted, raw


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


def _inbound_span(index: DocumentIndex, hit: InRef) -> Span:
    clause = index.by_id[hit.clause]
    if hit.heading:
        return clause.id, 0, len(clause.text)
    a, b = expand_quote(clause.text, hit.ref.start, hit.ref.end)
    return clause.id, a, b


def _parents(number: str) -> list[str]:
    parts = number.split(".")
    return [".".join(parts[:k]) for k in range(1, len(parts))]


def _mark(index: DocumentIndex, cid: str, ev: _Eval) -> None:
    span = index.info[cid].exception
    if span is not None:
        ev.reasons.add(Reason.check_exceptions)
        ev.attach(span)


def _exceptions(
    index: DocumentIndex,
    quoted: dict[str, Clause],
    closure: dict[str, ClosureEntry],
    topic_ids: Collection[str],
    ev: _Eval,
) -> None:
    """Exception markers in the quoted clauses, their parents, their outgoing references, the
    clauses of the topic; and any other clause that names a quoted clause."""
    for cid, clause in quoted.items():
        _mark(index, cid, ev)
        parents = (
            pid
            for number in _parents(clause.number or "")
            for pid in index.numbers.by_number.get(number, ())
        )
        for other in (*parents, *closure[cid].added):
            if other not in quoted:
                _mark(index, other, ev)
    for cid in sorted(topic_ids):
        if cid in index.info and cid not in quoted:
            _mark(index, cid, ev)
    for clause in quoted.values():
        if clause.number is None:
            continue
        for hit in index.inbound_to(clause.number):
            if hit.clause not in quoted:
                ev.reasons.add(Reason.check_exceptions)
                if len(ev.attached) < MAX_ATTACHED:
                    ev.attach(_inbound_span(index, hit))


def _number_ok(index: DocumentIndex, spans: list[Span], number: NumericValue) -> bool:
    found: set[Decimal | None] = set()
    for cid, a, b in spans:
        found |= number_values(index.by_id[cid].text[a:b], number.unit)
    return found == {number.number}


def _evaluate(
    ctx: DocumentContext,
    index: DocumentIndex,
    evidence: Sequence[Evidence],
    topic: str | None,
    number: NumericValue | None,
) -> _Eval:
    ev = _Eval()
    quoted, raw = _quotes(index, evidence, ev)
    reasons = ev.reasons
    flags = {
        Reason.unverified: not ev.verified,
        Reason.other_not_green: topic is None,
        Reason.incomplete: ctx.incomplete,
        Reason.document_flags: bool(ctx.flags or ctx.unprovided_reference_clauses & quoted.keys()),
        Reason.quote_too_short: any(s[2] - s[1] < MIN_QUOTE_CHARS for s in ev.verified),
        Reason.unresolved_reference: any(index.info[cid].unresolved for cid in quoted),
        Reason.global_override: bool(index.overrides),
    }
    reasons.update(reason for reason, on in flags.items() if on)
    for span in index.overrides[:MAX_ATTACHED]:
        ev.attach(span)
    closure = {cid: index.numbers.resolve(index.info[cid].refs, cid, MAX_REFS) for cid in quoted}
    if any(entry.too_many for entry in closure.values()):
        reasons.add(Reason.too_many_references)
    _suspicious(ctx, quoted, raw, ev)
    topic_ids = ctx.topic_clauses.get(topic, ()) if topic is not None else ()
    _exceptions(index, quoted, closure, topic_ids, ev)
    if number is not None and ev.verified and not _number_ok(index, ev.verified, number):
        reasons.add(Reason.number_mismatch)
    return ev


def _ordered(reasons: set[Reason]) -> tuple[Reason, ...]:
    return tuple(r for r in Reason if r in reasons)


def apply_green_rules(
    ctx: DocumentContext, finding: Finding, index: DocumentIndex | None = None
) -> RatedFinding:
    """Cap a green to yellow when a rule fails. Yellow and red never change.

    ``index`` is ``build_document_index(ctx.clauses)``; it is built here when missing."""
    idx = index if index is not None else build_document_index(ctx.clauses)
    ev = _evaluate(ctx, idx, finding.evidence, finding.topic, finding.value)
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


def verify_value(
    ctx: DocumentContext, value: ValueIn, index: DocumentIndex | None = None
) -> ValueOut:
    """``verified`` only with a verified quote, a passing number check and no cap."""
    idx = index if index is not None else build_document_index(ctx.clauses)
    ev = _evaluate(ctx, idx, value.evidence, value.topic, value.number)
    reasons = ev.reasons - _VALUE_IGNORED
    return ValueOut(
        ValueStatus.not_confirmed if reasons else ValueStatus.verified, _ordered(reasons)
    )
