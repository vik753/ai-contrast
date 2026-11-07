"""Verification of the model answers and the events of a result (ADR 0019 points 2 and 3).

Pure: plain data in, plain data out (ids, enums, numbers, offsets and cleaned explanations;
never clause text, topic text or quotes). Quotes are mapped to the SOURCE text first, then
``app.analysis.verify`` checks them. A green that fails a rule becomes yellow with reason codes;
a high Layer 2 hit anywhere removes every green. Nothing here logs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from app.analysis.execute import Executed, OtherRun, TopicRun
from app.analysis.plan import AnalysisPlan, AnalysisRequest, DocFacts
from app.analysis.schemas import (
    AmountValue,
    DurationValue,
    EvidenceOut,
    FindingOut,
    PercentageValue,
)
from app.analysis.source_map import NeutralView, neutral_view, source_quote
from app.analysis.verify import (
    DocumentContext,
    Evidence,
    Finding,
    NumericValue,
    RatedFinding,
    Rating,
    Reason,
    TaggingState,
    TopicInfo,
    TopicState,
    ValueIn,
    apply_green_rules,
    missing_topic_findings,
    verify_value,
)

__all__ = ["EVENT_DATA_LIMIT", "Assembled", "assemble"]

EVENT_DATA_LIMIT: Final = 60_000  # bytes of one event's JSON; the hard cap is 64 KiB with framing


@dataclass
class Assembled:
    topic_events: list[dict[str, Any]] = field(default_factory=list)
    other_events: list[dict[str, Any]] = field(default_factory=list)
    unrated_other: int = 0
    incomplete: bool = False
    greens_allowed: bool = True
    not_analyzed: list[dict[str, str]] = field(default_factory=list)
    result_hash: str = ""


def _numeric(value: object) -> NumericValue | None:
    if isinstance(value, AmountValue):
        return NumericValue(Decimal(repr(value.number)), value.currency)
    if isinstance(value, PercentageValue):
        return NumericValue(Decimal(repr(value.number)), None)
    if isinstance(value, DurationValue):
        return NumericValue(Decimal(repr(value.number)), value.unit)
    return None


def _spans(spans: Sequence[tuple[str, int, int]]) -> list[list[Any]]:
    return [[c, s, e] for c, s, e in spans]


class _Verifier:
    def __init__(self, facts: DocFacts, req: AnalysisRequest, incomplete: bool) -> None:
        self.facts = facts
        self.req = req
        self.incomplete = incomplete
        self._views: dict[str, NeutralView | None] = {}

    def evidence(self, items: Sequence[EvidenceOut]) -> tuple[Evidence, ...]:
        out = []
        for item in items:
            clause = self.facts.index.by_id.get(item.clause)
            if clause is None:
                out.append(Evidence(item.clause, item.quote))
                continue
            if clause.id not in self._views:
                self._views[clause.id] = neutral_view(clause.text)
            out.append(
                Evidence(clause.id, source_quote(clause, item.quote, self._views[clause.id]))
            )
        return tuple(out)

    def context(
        self, topic_clauses: dict[str, frozenset[str]], injection: tuple[Evidence, ...]
    ) -> DocumentContext:
        facts = self.facts
        return DocumentContext(
            clauses=facts.clauses,
            topic_clauses=topic_clauses,
            flags=self.req.flags,
            unprovided_reference_clauses=facts.unprovided,
            layer2_spans=facts.layer2_spans,
            layer2_heuristic_clauses=facts.layer2_heuristic,
            injection=injection,
            incomplete=self.incomplete,
        )

    def finding(
        self,
        ctx: DocumentContext,
        out: FindingOut,
        topic: str | None,
        number: NumericValue | None,
    ) -> dict[str, Any]:
        item = Finding(
            Rating(out.rating), self.evidence(out.evidence), topic, out.attribute, number
        )
        rated: RatedFinding = apply_green_rules(ctx, item, self.facts.index)
        rating, reasons = rated.rating, set(rated.reasons)
        if rating is Rating.green and self.facts.layer2_high:
            rating = Rating.yellow
            reasons.add(Reason.suspicious_span)
        return {
            "rating": rating.value,
            "attribute": out.attribute,
            "explanation": out.explanation,
            "reasons": [r.value for r in Reason if r in reasons],
            "unverified": rated.unverified,
            "evidence": _spans(rated.verified_spans),
            "attached": _spans(rated.attached),
        }

    def topic_run(self, run: TopicRun, topic_sets: dict[str, frozenset[str]]) -> dict[str, Any]:
        out = run.output
        assert out is not None  # noqa: S101 - callers pass finished runs only
        tid = run.plan.topic.topic_id
        injection = tuple(e for item in out.injection_suspected for e in self.evidence([item]))
        ctx = self.context(topic_sets, injection)
        numbers = {a.attribute: _numeric(a.value) for a in out.attributes}
        values = []
        for attr in out.attributes:
            number = numbers[attr.attribute]
            evidence = self.evidence(attr.evidence)
            checked = verify_value(
                ctx, ValueIn(attr.attribute, evidence, tid, number), self.facts.index
            )
            probe = apply_green_rules(
                ctx, Finding(Rating.yellow, evidence, tid, attr.attribute, number), self.facts.index
            )
            values.append(
                {
                    "attribute": attr.attribute,
                    "value": attr.value.model_dump(mode="json"),
                    "status": checked.status.value,
                    "reasons": [r.value for r in checked.reasons],
                    "evidence": _spans(probe.verified_spans),
                }
            )
        findings = [
            self.finding(ctx, f, tid, numbers.get(f.attribute) if f.attribute else None)
            for f in out.findings
        ]
        return {"values": values, "findings": findings}

    def other_entries(self, run: OtherRun) -> list[tuple[str, bool, list[dict[str, Any]]]]:
        out = run.output
        assert out is not None  # noqa: S101
        ctx = self.context({}, ())
        by_clause = {item.clause: item for item in out.clauses}
        entries = []
        for cid in run.ids:
            item = by_clause[cid]
            found = []
            for f in item.findings:
                body = self.finding(ctx, f, None, None)
                found.append({"clause": cid, **body})
            entries.append((cid, item.no_issue, found))
        return entries


def _split(
    run: OtherRun, entries: list[tuple[str, bool, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    current: list[tuple[str, bool, list[dict[str, Any]]]] = []
    size = 0

    def flush() -> None:
        parts.append(
            {
                "batch": run.batch,
                "part": len(parts),
                "clauses": [c for c, _, _ in current],
                "rated": True,
                "reason": None,
                "no_issue": [c for c, quiet, _ in current if quiet],
                "findings": [f for _, _, found in current for f in found],
            }
        )

    for entry in entries:
        weight = len(json.dumps(entry[2], ensure_ascii=False).encode()) + 40
        if current and size + weight > EVENT_DATA_LIMIT:
            flush()
            current, size = [], 0
        current.append(entry)
        size += weight
    flush()
    return parts


def assemble(
    facts: DocFacts, plan: AnalysisPlan, executed: Executed, req: AnalysisRequest
) -> Assembled:
    unrated = sum(len(o.ids) for o in executed.others if o.output is None)
    incomplete = unrated > 0
    verifier = _Verifier(facts, req, incomplete)
    topic_sets = {p.topic.topic_id: frozenset(p.sent) for p in plan.topics if p.callable}
    missing = {
        m.topic: m.rating
        for m in missing_topic_findings(
            TaggingState(complete=plan.complete, signed=True),
            [TopicInfo(p.topic.topic_id, len(p.tagged), p.state, p.essential) for p in plan.topics],
        )
    }
    result = Assembled(unrated_other=unrated, incomplete=incomplete)
    for run in executed.topics:
        p = run.plan
        tid = p.topic.topic_id
        event: dict[str, Any] = {
            "topic_id": tid,
            "state": p.state.value,
            "reason": p.reason,
            "clauses": list(p.sent) if p.callable else [],
            "missing": {"rating": missing[tid].value} if tid in missing else None,
            "values": [],
            "findings": [],
        }
        if p.callable and run.output is None:
            event["state"] = TopicState.not_analyzed.value
            event["reason"] = run.failure
        elif p.callable:
            event.update(verifier.topic_run(run, topic_sets))
        if event["state"] == TopicState.not_analyzed.value:
            result.not_analyzed.append({"topic_id": tid, "reason": str(event["reason"])})
        result.topic_events.append(event)
    for other in executed.others:
        if other.output is None:
            result.other_events.append(
                {
                    "batch": other.batch,
                    "part": 0,
                    "clauses": list(other.ids),
                    "rated": False,
                    "reason": other.failure,
                    "no_issue": [],
                    "findings": [],
                }
            )
        else:
            result.other_events.extend(_split(other, verifier.other_entries(other)))
    result.greens_allowed = not (
        incomplete or req.flags or facts.layer2_high or facts.index.overrides
    )
    blob = json.dumps(
        [result.topic_events, result.other_events], sort_keys=True, ensure_ascii=False
    )
    result.result_hash = hashlib.sha256(blob.encode()).hexdigest()
    return result
