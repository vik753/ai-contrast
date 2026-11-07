"""The event stream of one analysis (ADR 0019 points 1 and 8): ``start``, the AI phases,
verification, then ``topic`` and ``other`` events and ``done`` (or ``error``). Everything that
touches gate types is here, not in the route module. Events hold ids, enums, numbers, offsets
and cleaned explanations only. Nothing here logs.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

from app.ai.port import AIError, ReasoningEffort
from app.analysis.assemble import assemble
from app.analysis.execute import CountingProvider, execute
from app.analysis.plan import AnalysisPlan, AnalysisRequest, DocFacts
from app.analysis.signature import ResultSigner, analysis_version
from app.pseudo.gate import PseudonymizedDocument
from app.topics.catalog import Catalog

__all__ = ["Emit", "stream_analysis"]

Emit = Callable[[str, dict[str, Any]], None]


def _flags_hash(req: AnalysisRequest) -> str:
    parts = ["flags", *sorted(f.value for f in req.flags), "annex", *sorted(req.annex_links)]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


async def stream_analysis(  # noqa: PLR0913, PLR0917
    document: PseudonymizedDocument,
    digest: str,
    plan: AnalysisPlan,
    req: AnalysisRequest,
    facts: DocFacts,
    provider: CountingProvider,
    catalog: Catalog,
    deadline: float,
    effort: ReasoningEffort | None,
    signer: ResultSigner,
    emit: Emit,
) -> bool:
    """Emit the events. Returns ``False`` when a hard provider error ended the stream (the
    ``error`` event is sent); raises only on cancellation or an internal failure."""
    emit(
        "start",
        {
            "digest": digest,
            "topics": len(plan.topics),
            "other_batches": plan.other_batches,
            "reserved_calls": plan.calls,
        },
    )

    def progress(done: int, total: int) -> None:
        emit("progress", {"done": done, "total": total})

    try:
        executed = await execute(document, plan, req, provider, catalog, deadline, effort, progress)
    except AIError as error:
        emit("error", {"error": error.code.value})
        return False
    assembled = await asyncio.to_thread(assemble, facts, plan, executed, req)
    for event in assembled.topic_events:
        emit("topic", event)
    for other in assembled.other_events:
        emit("other", other)
    version = analysis_version()
    emit(
        "done",
        {
            "digest": digest,
            "incomplete": assembled.incomplete,
            "unrated_other": assembled.unrated_other,
            "greens_allowed": assembled.greens_allowed,
            "not_analyzed": assembled.not_analyzed,
            "flags": sorted(f.value for f in req.flags),
            "result_signature": signer.sign(
                digest=digest,
                version=version,
                domain=req.domain,
                side=req.side,
                model=req.model,
                language=req.language.value,
                flags_hash=_flags_hash(req),
                result_hash=assembled.result_hash,
            ),
            "analysis_version": version,
        },
    )
    return True
