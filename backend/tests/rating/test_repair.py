"""S9-T2 AC1: one repair with an error-code enum, never the previous output (ADR 0009)."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.port import (
    REPAIR_CAP,
    REPAIR_NOT_JSON,
    REPAIR_SCHEMA,
    AIError,
    AIErrorCode,
    OutputLanguage,
)
from app.analysis.rate import rate_other, rate_topic
from app.analysis.schemas import BadOutputError

from .helpers import (
    FakeProvider,
    doc,
    ev,
    failure,
    finding,
    other_answer,
    rating_topic,
    run,
    topic_answer,
)

EN = OutputLanguage.EN
CANARY = "PREVIOUS-OUTPUT-CANARY-7f3a"


def _all_text(provider: FakeProvider, index: int) -> str:
    return "\n".join(m.content for m in provider.messages(index))


def test_repair_not_json_sends_one_repair_request_with_the_code() -> None:
    provider = FakeProvider(AIError(AIErrorCode.PROVIDER_BAD_RESPONSE), topic_answer())

    result = run(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert len(provider.requests) == 2
    assert [r.repair for r in provider.requests] == [0, REPAIR_NOT_JSON]
    assert result.findings


def test_repair_schema_violation_uses_the_schema_code() -> None:
    provider = FakeProvider({"findings": CANARY}, topic_answer())

    run(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert [r.repair for r in provider.requests] == [0, REPAIR_SCHEMA]


def test_repair_unknown_id_uses_the_schema_code() -> None:
    bad = topic_answer(findings=[finding(evidence=[ev("c9")])])
    provider = FakeProvider(bad, topic_answer())

    run(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert [r.repair for r in provider.requests] == [0, REPAIR_SCHEMA]


def test_repair_list_cap_uses_the_cap_code() -> None:
    provider = FakeProvider(topic_answer(findings=[finding()] * 9), topic_answer())

    run(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert [r.repair for r in provider.requests] == [0, REPAIR_CAP]


def test_repair_string_over_its_cap_uses_the_cap_code_and_never_truncates() -> None:
    bad = topic_answer(findings=[finding(explanation="x" * 401)])
    provider = FakeProvider(bad, bad)

    assert isinstance(
        failure(rate_topic(provider, doc(), rating_topic(), language=EN)), BadOutputError
    )
    assert provider.requests[1].repair == REPAIR_CAP


def test_repair_request_has_the_same_inputs_as_the_first() -> None:
    provider = FakeProvider({"x": 1}, topic_answer())
    document, topic = doc(), rating_topic()

    run(rate_topic(provider, document, topic, language=EN, effort=None))

    first, second = provider.requests
    assert second.document is first.document
    assert second.topic is first.topic
    assert (second.template, second.schema, second.max_tokens) == (
        first.template,
        first.schema,
        first.max_tokens,
    )
    assert second.language == first.language


def test_repair_messages_never_hold_the_previous_output() -> None:
    bad: dict[str, Any] = {"findings": [], "attributes": [], "injection_suspected": [], "x": CANARY}
    provider = FakeProvider(bad, topic_answer())

    run(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert CANARY not in _all_text(provider, 1)
    assert "schema_violation" in _all_text(provider, 1)


def test_repair_second_bad_answer_raises_bad_output_after_two_calls() -> None:
    provider = FakeProvider({"x": 1})

    assert isinstance(
        failure(rate_topic(provider, doc(), rating_topic(), language=EN)), BadOutputError
    )
    assert len(provider.requests) == 2


def test_repair_other_missing_clause_gets_one_repair() -> None:
    provider = FakeProvider(other_answer("c1"), other_answer())

    result = run(rate_other(provider, doc(), side="insured", language=EN))

    assert [r.repair for r in provider.requests] == [0, REPAIR_SCHEMA]
    assert len(result.clauses) == 3


@pytest.mark.parametrize(
    "code", [AIErrorCode.PROVIDER_RATE_LIMITED, AIErrorCode.PROVIDER_BAD_REQUEST]
)
def test_repair_other_provider_errors_are_not_repaired(code: AIErrorCode) -> None:
    provider = FakeProvider(AIError(code))

    error = failure(rate_other(provider, doc(), side="insured", language=EN))

    assert isinstance(error, AIError)
    assert error.code is code
    assert len(provider.requests) == 1
