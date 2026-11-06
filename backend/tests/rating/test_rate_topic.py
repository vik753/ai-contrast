"""S9-T2 AC1: rate_topic checks the answer against the request (ids, units, value ids)."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.port import AIError, AIErrorCode, OutputLanguage
from app.analysis.rate import rate_topic
from app.analysis.schemas import BadOutputError

from .helpers import (
    FakeProvider,
    doc,
    ev,
    failure,
    finding,
    rating_topic,
    run,
    topic_answer,
)

EN = OutputLanguage.EN


def _attrs(*items: dict[str, Any]) -> dict[str, Any]:
    return topic_answer(attributes=list(items), findings=[])


def _attr(name: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"attribute": name, "value": value, "evidence": [ev()]}


def _rate(answer: dict[str, Any]) -> Any:
    provider = FakeProvider(answer)
    return run(rate_topic(provider, doc(), rating_topic(), language=EN))


def test_rate_topic_valid_answer_returns_typed_result() -> None:
    result = _rate(topic_answer())

    assert [a.attribute for a in result.attributes] == ["limit", "delay"]
    assert result.findings[0].rating == "yellow"
    assert result.injection_suspected == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("limit", {"type": "amount", "number": 100, "currency": "USD"}),
        ("delay", {"type": "duration", "number": 5, "unit": "working_days"}),
        ("share", {"type": "percentage", "number": 20}),
        ("cover", {"type": "enum", "value": "full_cover"}),
        ("extras", {"type": "categories", "values": ["extra_taxi", "extra_towing"]}),
        ("note", {"type": "text", "text": "a remark"}),
        ("note", {"type": "not_stated"}),
        ("limit", {"type": "not_stated"}),
    ],
)
def test_rate_topic_accepts_each_value_type_for_its_attribute(
    name: str, value: dict[str, Any]
) -> None:
    _rate(_attrs(_attr(name, value)))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("limit", {"type": "amount", "number": 1, "currency": "EUR"}),  # unit not of the attribute
        ("limit", {"type": "amount", "number": 1, "currency": "percent_of_sum"}),
        ("delay", {"type": "duration", "number": 1, "unit": "months"}),
        ("delay", {"type": "amount", "number": 1, "currency": "UAH"}),  # type differs
        ("share", {"type": "amount", "number": 1, "currency": "UAH"}),
        ("cover", {"type": "enum", "value": "gold_cover"}),  # unknown value id
        ("cover", {"type": "enum", "value": "basic"}),  # label, not id
        ("extras", {"type": "categories", "values": ["extra_taxi", "extra_taxi"]}),
        ("extras", {"type": "categories", "values": ["extra_plane"]}),
        ("note", {"type": "enum", "value": "basic_cover"}),
        ("unknown_attr", {"type": "not_stated"}),
    ],
)
def test_rate_topic_value_not_fitting_the_topic_is_bad_output(
    name: str, value: dict[str, Any]
) -> None:
    provider = FakeProvider(_attrs(_attr(name, value)))

    assert isinstance(
        failure(rate_topic(provider, doc(), rating_topic(), language=EN)), BadOutputError
    )


def test_rate_topic_attribute_listed_twice_is_bad_output() -> None:
    one = _attr("limit", {"type": "not_stated"})
    provider = FakeProvider(_attrs(one, one))

    assert isinstance(
        failure(rate_topic(provider, doc(), rating_topic(), language=EN)), BadOutputError
    )


@pytest.mark.parametrize(
    "answer",
    [
        topic_answer(findings=[finding(evidence=[ev("c9")])]),
        topic_answer(injection_suspected=[ev("c9", "x")]),
        _attrs({"attribute": "limit", "value": {"type": "not_stated"}, "evidence": [ev("c4")]}),
        topic_answer(findings=[finding(attribute="nope")]),
    ],
    ids=["finding_clause", "injection_clause", "attribute_clause", "finding_attribute"],
)
def test_rate_topic_unknown_clause_or_attribute_id_is_bad_output(answer: dict[str, Any]) -> None:
    provider = FakeProvider(answer)

    assert isinstance(
        failure(rate_topic(provider, doc(), rating_topic(), language=EN)), BadOutputError
    )
    assert len(provider.requests) == 2


def test_rate_topic_hard_provider_error_is_raised_without_repair() -> None:
    provider = FakeProvider(AIError(AIErrorCode.PROVIDER_AUTH_FAILED))

    error = failure(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert isinstance(error, AIError)
    assert error.code is AIErrorCode.PROVIDER_AUTH_FAILED
    assert len(provider.requests) == 1


def test_rate_topic_unavailable_provider_is_raised_without_repair() -> None:
    provider = FakeProvider(AIError(AIErrorCode.PROVIDER_UNAVAILABLE))

    error = failure(rate_topic(provider, doc(), rating_topic(), language=EN))

    assert isinstance(error, AIError)
    assert len(provider.requests) == 1


def test_rate_topic_makes_one_call_with_one_document_and_the_topic() -> None:
    provider = FakeProvider(topic_answer())
    document, topic = doc(), rating_topic()

    run(rate_topic(provider, document, topic, language=EN))

    assert len(provider.requests) == 1
    assert provider.requests[0].document is document
    assert provider.requests[0].topic is topic
