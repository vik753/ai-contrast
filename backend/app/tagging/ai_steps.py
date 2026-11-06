"""The model steps of tagging (ADR 0018 point 3): tagging calls with the cheap model, check calls
with the strong model, one repair per call, and fallbacks that never fail the request.

Hard provider errors (key, model, request, blocked host) are raised as ``AIError`` for the
endpoint to answer. Every other failure is a reason in ``ModelState.failures`` and the batch
keeps only what code found. Results are written to ``ModelState`` as each call ends, so a
request that hits its overall deadline keeps what it has. Nothing here logs; no model text is
kept beyond the validated ids.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from pydantic import ValidationError

from app.ai.port import (
    REPAIR_CAP,
    REPAIR_NOT_JSON,
    REPAIR_SCHEMA,
    AIError,
    AIErrorCode,
    AIProvider,
    AIRequest,
    ModelJson,
    TaggingRequest,
)
from app.ai.prompts import PromptTemplate
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument, subset_document
from app.tagging.batches import check_max_tokens, tag_max_tokens
from app.tagging.schemas import (
    BadOutputError,
    CheckOut,
    TagOut,
    checked_answers,
    checked_tags,
)

__all__ = ["HARD_CODES", "ModelState", "run_model_steps"]

HARD_CODES: Final = frozenset(
    {
        AIErrorCode.PROVIDER_AUTH_FAILED,
        AIErrorCode.PROVIDER_MODEL_NOT_FOUND,
        AIErrorCode.PROVIDER_BAD_REQUEST,
        AIErrorCode.PROVIDER_BLOCKED_HOST,
    }
)
_SOFT_REASON: Final = {
    AIErrorCode.PROVIDER_UNAVAILABLE: "timeout",
    AIErrorCode.PROVIDER_RATE_LIMITED: "quota",
    AIErrorCode.PROVIDER_BAD_RESPONSE: "bad_output",
}
ATTEMPTS: Final = 2  # one call and one repair call


@dataclass
class ModelState:
    """What the model steps found. Topic ids, not numbers."""

    high: dict[str, set[str]] = field(default_factory=dict)
    low: dict[str, set[str]] = field(default_factory=dict)
    check_yes: dict[str, set[str]] = field(default_factory=dict)
    failures: set[str] = field(default_factory=set)
    calls: int = 0
    completed: int = 0  # calls that returned an answer (the provider reports their usage)


async def _complete[ResultT](
    provider: AIProvider,
    make: Callable[[int], AIRequest],
    check: Callable[[ModelJson], ResultT],
    state: ModelState,
    deadline: float,
) -> ResultT:
    """One call and at most one repair call (same inputs plus a fixed error code)."""
    repair = 0
    for _ in range(ATTEMPTS):
        state.calls += 1
        try:
            async with asyncio.timeout(deadline):
                raw = await provider.complete_json(make(repair))
            state.completed += 1
        except AIError as error:
            if error.code is not AIErrorCode.PROVIDER_BAD_RESPONSE:
                raise
            repair = REPAIR_NOT_JSON
            continue
        except TimeoutError:
            raise AIError(AIErrorCode.PROVIDER_UNAVAILABLE) from None
        try:
            return check(raw)
        except ValidationError as error:
            repair = (
                REPAIR_CAP
                if any(item["type"] == "too_long" for item in error.errors())
                else REPAIR_SCHEMA
            )
        except BadOutputError:
            repair = REPAIR_SCHEMA
    raise BadOutputError


def _record(target: dict[str, set[str]], clause_id: str, topic_ids: set[str]) -> None:
    if topic_ids:
        target.setdefault(clause_id, set()).update(topic_ids)


def _failure(state: ModelState, error: AIError, *, check: bool) -> None:
    if error.code in HARD_CODES:
        raise error
    state.failures.add("check_failed" if check else _SOFT_REASON[error.code])


async def _tag_batch(
    provider: AIProvider,
    sub: PseudonymizedDocument,
    topics: Sequence[ConfirmedTopic],
    state: ModelState,
    deadline: float,
) -> tuple[dict[str, set[int]], dict[str, set[int]]] | None:
    ids = {clause.id for clause in sub.clauses}
    size = len(ids)

    def make(repair: int) -> AIRequest:
        return TaggingRequest(
            PromptTemplate.TAG_CLAUSES,
            TagOut,
            tag_max_tokens(size),
            document=sub,
            topics=tuple(topics),
            repair=repair,
        )

    def check(raw: ModelJson) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
        return checked_tags(TagOut.model_validate(raw), ids, len(topics))

    try:
        return await _complete(provider, make, check, state, deadline)
    except BadOutputError:
        state.failures.add("bad_output")
    except AIError as error:
        _failure(state, error, check=False)
    return None


async def _check_batch(  # noqa: PLR0913, PLR0917
    provider: AIProvider,
    document: PseudonymizedDocument,
    topics: Sequence[ConfirmedTopic],
    pairs: list[tuple[str, int]],
    state: ModelState,
    deadline: float,
) -> set[tuple[str, int]] | None:
    sub = subset_document(document, sorted({clause for clause, _ in pairs}))
    numbers = tuple(sorted({number for _, number in pairs}))
    position = {clause.id: index for index, clause in enumerate(sub.clauses)}

    def make(repair: int) -> AIRequest:
        return TaggingRequest(
            PromptTemplate.CHECK_TAGS,
            CheckOut,
            check_max_tokens(len(pairs)),
            document=sub,
            topics=tuple(topics),
            pairs=tuple((position[clause], number) for clause, number in pairs),
            topic_numbers=numbers,
            repair=repair,
        )

    def check(raw: ModelJson) -> set[tuple[str, int]]:
        return checked_answers(CheckOut.model_validate(raw), pairs)

    try:
        return await _complete(provider, make, check, state, deadline)
    except BadOutputError:
        state.failures.add("check_failed")
    except AIError as error:
        _failure(state, error, check=True)
    return None


async def run_model_steps(  # noqa: PLR0913, PLR0917
    document: PseudonymizedDocument,
    topics: Sequence[ConfirmedTopic],
    batches: Sequence[Sequence[str]],
    tag_provider: AIProvider,
    check_provider: AIProvider,
    state: ModelState,
    call_deadline: float,
) -> None:
    """Tag and check the batches in order. Raises ``AIError`` for a hard provider error."""
    topic_ids = [topic.topic_id for topic in topics]
    order = {clause.id: index for index, clause in enumerate(document.clauses)}
    for ids in batches:
        sub = subset_document(document, list(ids))
        found = await _tag_batch(tag_provider, sub, topics, state, call_deadline)
        if found is None:
            continue
        high, low = found
        for clause_id, numbers in high.items():
            _record(state.high, clause_id, {topic_ids[n - 1] for n in numbers})
        pairs = sorted(
            ((clause_id, n) for clause_id, numbers in low.items() for n in numbers),
            key=lambda pair: (order[pair[0]], pair[1]),
        )
        if not pairs:
            continue
        yes = await _check_batch(check_provider, document, topics, pairs, state, call_deadline)
        if yes is None:
            continue
        for clause_id, number in pairs:
            _record(state.low, clause_id, {topic_ids[number - 1]})
            if (clause_id, number) in yes:
                _record(state.check_yes, clause_id, {topic_ids[number - 1]})
