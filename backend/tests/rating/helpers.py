"""Helpers of the S9-T2 tests (see README.md). Synthetic data, fake provider, no network."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable
from typing import Any

from app.ai.port import AIRequest, CheckResult, ModelJson
from app.ai.prompting import Message, build_messages
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument
from app.topics.catalog import load_catalog
from tests.ai.helpers import make_document
from tests.topics.helpers import CATALOG_OK, attribute, confirmed

DOMAIN = "kasko"
CATALOG = load_catalog(CATALOG_OK)
SYNONYM = "zzcanarysynonym"
DIRECTIONS = ("lower_better", "higher_better", "more_better", "fewer_better")
TEXTS = (
    "1. Towing is covered up to 5000 UAH per event.",
    "2. The Insurer pays within 10 days.",
    "3. The cover is full.",
)


class FakeProvider:
    """Answers in order (the last repeats). An exception is raised, anything else returned."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.requests: list[AIRequest] = []
        self.usage = None

    async def check(self) -> CheckResult:
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return copy.deepcopy(answer)  # type: ignore[no-any-return]

    def messages(self, index: int = 0) -> tuple[Message, ...]:
        return build_messages(self.requests[index])


def doc(*texts: str, label: str = "A") -> PseudonymizedDocument:
    return make_document(*(texts or TEXTS), label=label)


def rating_topic() -> ConfirmedTopic:
    attrs = (
        attribute(
            id="limit",
            label="Towing limit",
            type="amount",
            units=("UAH", "USD"),
            direction="lower_better",
        ),
        attribute(
            id="delay",
            label="Payment delay",
            type="duration",
            units=("days", "working_days"),
            direction="lower_better",
        ),
        attribute(id="share", label="Own share", type="percentage", direction="higher_better"),
        attribute(
            id="cover",
            label="Cover level",
            type="enum",
            values=("basic", "full"),
            value_ids=("basic_cover", "full_cover"),
        ),
        attribute(
            id="extras",
            label="Extra services",
            type="categories",
            values=("towing", "taxi"),
            value_ids=("extra_towing", "extra_taxi"),
            direction="more_better",
        ),
        attribute(id="note", label="Remark", type="text"),
    )
    return confirmed(
        attributes=attrs,
        synonyms_en=(SYNONYM,),
        title="Roadside assistance",
        description="Towing and help on the road",
    )


def ev(clause: str = "c1", quote: str = "up to 5000 UAH") -> dict[str, str]:
    return {"clause": clause, "quote": quote}


def finding(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "rating": "yellow",
        "attribute": "limit",
        "explanation": "The limit is low for a long tow.",
        "evidence": [ev()],
    }
    return {**base, **changes}


def topic_answer(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "attributes": [
            {
                "attribute": "limit",
                "value": {"type": "amount", "number": 5000, "currency": "UAH"},
                "evidence": [ev()],
            },
            {
                "attribute": "delay",
                "value": {"type": "duration", "number": 10, "unit": "days"},
                "evidence": [ev("c2", "within 10 days")],
            },
        ],
        "findings": [finding()],
        "injection_suspected": [],
    }
    return {**base, **changes}


def other_answer(*ids: str) -> dict[str, Any]:
    ids = ids or ("c1", "c2", "c3")
    return {
        "clauses": [{"clause": i, "no_issue": True, "findings": []} for i in ids],
    }


def other_finding_clause(clause: str = "c2", **changes: Any) -> dict[str, Any]:
    return {
        "clause": clause,
        "no_issue": False,
        "findings": [
            finding(attribute=None, evidence=[ev(clause, "pays within 10 days")], **changes)
        ],
    }


def run[T](awaitable: Awaitable[T]) -> T:
    async def go() -> T:
        return await awaitable

    return asyncio.run(go())


def failure(awaitable: Awaitable[object]) -> BaseException:
    try:
        run(awaitable)
    except BaseException as error:  # noqa: BLE001
        return error
    raise AssertionError("no exception was raised")  # noqa: TRY003


def system_text(messages: tuple[Message, ...]) -> str:
    return "\n".join(m.content for m in messages if m.role == "system")
