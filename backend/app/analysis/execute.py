"""The AI phases of one analysis (ADR 0019 points 2, 3.7 and 7): topic calls, then the "Other"
calls over the "Other" clauses plus the clauses of every topic that failed. One document per
call. Hard provider errors are raised as ``AIError``; every other failure is a reason on the
run. An overall deadline stops the open calls; the open runs get the reason ``timeout``.
Nothing here logs; no model text is kept beyond the validated answers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.ai.port import (
    AIError,
    AIErrorCode,
    AIProvider,
    AIRequest,
    CheckResult,
    ModelJson,
    OutputLanguage,
    ReasoningEffort,
    Usage,
)
from app.analysis.plan import AnalysisPlan, AnalysisRequest, TopicPlan, pack
from app.analysis.rate import rate_other, rate_topic
from app.analysis.schemas import BadOutputError, OtherRatingOut, TopicRatingOut
from app.analysis.verify import other_clause_ids
from app.pseudo.gate import PseudonymizedDocument, subset_document
from app.tagging.ai_steps import HARD_CODES
from app.tagging.risk_terms import scan_risk
from app.topics.catalog import Catalog

__all__ = ["CountingProvider", "Executed", "OtherRun", "TopicRun", "execute"]

PARALLEL: Final = 4
Progress = Callable[[int, int], None]


class CountingProvider:
    """Counts the calls made and the calls that returned, and bounds each call in time. A call
    over its deadline is cancelled and reported as ``provider_unavailable``."""

    def __init__(self, inner: AIProvider, call_deadline: float) -> None:
        self._inner = inner
        self._deadline = call_deadline
        self.calls = 0
        self.completed = 0

    @property
    def usage(self) -> Usage | None:
        return self._inner.usage

    async def check(self) -> CheckResult:
        return await self._inner.check()

    async def complete_json(self, request: AIRequest) -> ModelJson:
        self.calls += 1
        try:
            async with asyncio.timeout(self._deadline):
                raw = await self._inner.complete_json(request)
        except TimeoutError:
            raise AIError(AIErrorCode.PROVIDER_UNAVAILABLE) from None
        self.completed += 1
        return raw


@dataclass
class TopicRun:
    plan: TopicPlan
    output: TopicRatingOut | None = None
    failure: str | None = None


@dataclass
class OtherRun:
    batch: int
    ids: tuple[str, ...]
    output: OtherRatingOut | None = None
    failure: str | None = None


@dataclass
class Executed:
    topics: list[TopicRun] = field(default_factory=list)
    others: list[OtherRun] = field(default_factory=list)


@dataclass
class _Counter:
    done: int = 0
    total: int = 0
    report: Progress = lambda _done, _total: None

    def finish(self) -> None:
        self.done += 1
        self.total = max(self.total, self.done)
        self.report(self.done, self.total)


async def _run_all(jobs: Sequence[Callable[[], Awaitable[None]]], deadline_at: float) -> None:
    """Run the jobs, at most ``PARALLEL`` at a time, until ``deadline_at`` (loop time). The
    first hard error is raised after the open jobs are cancelled."""
    loop = asyncio.get_running_loop()
    gate = asyncio.Semaphore(PARALLEL)

    async def guarded(job: Callable[[], Awaitable[None]]) -> None:
        async with gate:
            await job()

    tasks = [asyncio.create_task(guarded(job)) for job in jobs]
    try:
        if tasks:
            done, _ = await asyncio.wait(
                tasks,
                timeout=max(0.0, deadline_at - loop.time()),
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                error = task.exception()
                if error is not None:
                    raise error
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _soft(error: AIError) -> str:
    if error.code in HARD_CODES:
        raise error
    return "timeout"


async def execute(  # noqa: PLR0913, PLR0917
    document: PseudonymizedDocument,
    plan: AnalysisPlan,
    req: AnalysisRequest,
    provider: AIProvider,
    catalog: Catalog,
    deadline: float,
    effort: ReasoningEffort | None,
    report: Progress,
) -> Executed:
    loop = asyncio.get_running_loop()
    deadline_at = loop.time() + deadline
    counter = _Counter(0, plan.topic_calls + plan.other_batches, report)
    language: OutputLanguage = req.language
    result = Executed(topics=[TopicRun(p) for p in plan.topics])

    def topic_job(run: TopicRun) -> Callable[[], Awaitable[None]]:
        async def job() -> None:
            sub = subset_document(document, run.plan.sent)
            try:
                run.output = await rate_topic(
                    provider, sub, run.plan.topic, language=language, effort=effort
                )
            except BadOutputError:
                run.failure = "bad_output"
            except AIError as error:
                run.failure = _soft(error)
            counter.finish()

        return job

    callable_runs = [run for run in result.topics if run.plan.callable]
    await _run_all([topic_job(run) for run in callable_runs], deadline_at)
    for run in callable_runs:
        if run.output is None and run.failure is None:
            run.failure = "timeout"

    moved = {
        run.plan.topic.topic_id: run.plan.tagged for run in callable_runs if run.failure is not None
    }
    final = other_clause_ids(plan.other, moved, set(moved))
    texts = {c.id: c.text for c in document.clauses}
    size = {cid: len(texts[cid]) for cid in final}
    risky = [c for c in final if scan_risk(texts[c])]
    risky_set = set(risky)
    ordered = [*risky, *(c for c in final if c not in risky_set)]
    batches = pack(ordered, size)
    counter.total = max(counter.total, counter.done + len(batches))
    result.others = [OtherRun(i, ids) for i, ids in enumerate(batches)]

    def other_job(run: OtherRun) -> Callable[[], Awaitable[None]]:
        async def job() -> None:
            sub = subset_document(document, run.ids, keep_order=True)
            try:
                run.output = await rate_other(
                    provider,
                    sub,
                    side=req.side,
                    language=language,
                    effort=effort,
                    domain=req.domain,
                    catalog=catalog,
                )
            except BadOutputError:
                run.failure = "bad_output"
            except AIError as error:
                run.failure = _soft(error)
            counter.finish()

        return job

    allowed = result.others[: plan.max_other_batches]
    for over in result.others[plan.max_other_batches :]:
        over.failure = "budget"  # more batches than the reservation holds: fail closed
    await _run_all([other_job(run) for run in allowed], deadline_at)
    for left in allowed:
        if left.output is None and left.failure is None:
            left.failure = "timeout"
    return result
