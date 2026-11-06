"""S9-T2 AC1 / ADR 0019 point 2: strict output schemas."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from app.analysis.schemas import BadOutputError, OtherRatingOut, TopicRatingOut
from app.tagging.schemas import BadOutputError as TaggingBadOutputError

from .helpers import ev, finding, other_answer, other_finding_clause, topic_answer

LONG = "\U0001d41a" * 400  # 400 code points, 1600 UTF-8 bytes


def _with(**changes: Any) -> dict[str, Any]:
    return topic_answer(**changes)


def _value(value: dict[str, Any]) -> dict[str, Any]:
    return _with(attributes=[{"attribute": "limit", "value": value, "evidence": []}])


def test_schema_valid_answer_passes() -> None:
    assert TopicRatingOut.model_validate(topic_answer()).findings[0].rating == "yellow"


def test_schema_bad_output_error_is_the_tagging_class() -> None:
    assert BadOutputError is TaggingBadOutputError


@pytest.mark.parametrize(
    "data",
    [
        _with(extra=1),
        _with(findings=[finding(extra=1)]),
        _with(findings=[finding(evidence=[{**ev(), "extra": 1}])]),
        _value({"type": "amount", "number": 1, "currency": "UAH", "extra": 1}),
        _with(findings=[finding(rating="orange")]),
        _with(findings=[finding(rating="GREEN")]),
        _with(findings=[finding(rating=None)]),
        _with(findings=[finding(explanation="")]),
        _with(findings=[finding(explanation="x" * 401)]),
        _with(findings=[finding(explanation="\U0001d41a" * 401)]),
        _with(findings=[finding(evidence=[])]),
        _with(findings=[finding(evidence=[ev()] * 4)]),
        _with(findings=[finding()] * 9),
        _with(injection_suspected=[ev()] * 4),
        _with(
            attributes=[
                {"attribute": "limit", "value": {"type": "not_stated"}, "evidence": [ev()] * 4}
            ]
        ),
        _with(
            attributes=[{"attribute": "limit", "value": {"type": "not_stated"}, "evidence": []}]
            * 13
        ),
        _with(findings=[finding(evidence=[ev("c0")])]),
        _with(findings=[finding(evidence=[ev("x1")])]),
        _with(findings=[finding(evidence=[ev(" c1")])]),
        _with(findings=[finding(evidence=[ev("c1; drop")])]),
        _with(findings=[finding(evidence=[ev(quote="")])]),
        _with(findings=[finding(evidence=[ev(quote="q" * 1001)])]),
        _with(findings="none"),
        {k: v for k, v in topic_answer().items() if k != "findings"},
    ],
)
def test_schema_topic_rating_refuses_extras_enums_and_caps(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TopicRatingOut.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        _with(findings=[finding(explanation=LONG)]),
        _with(findings=[finding(evidence=[ev()] * 3)]),
        _with(findings=[finding()] * 8),
        _with(injection_suspected=[ev()] * 3),
        _with(findings=[], attributes=[]),
        _with(findings=[finding(attribute=None)]),
    ],
)
def test_schema_topic_rating_accepts_values_at_the_cap(data: dict[str, Any]) -> None:
    TopicRatingOut.model_validate(data)


@pytest.mark.parametrize(
    "value",
    [
        {"type": "money", "number": 1},
        {"type": "amount", "number": 1},
        {"type": "amount", "number": 1, "currency": "RUB"},
        {"type": "amount", "number": 1, "currency": "usd"},
        {"type": "amount", "number": "5000", "currency": "UAH"},
        {"type": "amount", "number": True, "currency": "UAH"},
        {"type": "amount", "number": -1, "currency": "UAH"},
        {"type": "amount", "number": float("nan"), "currency": "UAH"},
        {"type": "amount", "number": float("inf"), "currency": "UAH"},
        {"type": "amount", "number": 1e13, "currency": "UAH"},
        {"type": "duration", "number": 3, "unit": "weeks"},
        {"type": "duration", "number": 3},
        {"type": "percentage"},
        {"type": "enum"},
        {"type": "enum", "value": "Not An Id"},
        {"type": "categories", "values": "a"},
        {"type": "categories", "values": ["extra_taxi"] * 31},
        {"type": "text", "text": "t" * 201},
        {"type": "not_stated", "number": 1},
        {"number": 1, "currency": "UAH"},
    ],
)
def test_schema_value_refuses_wrong_shapes(value: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TopicRatingOut.model_validate(_value(value))


@pytest.mark.parametrize(
    "value",
    [
        {"type": "amount", "number": 12.5, "currency": "percent_of_sum"},
        {"type": "percentage", "number": 20},
        {"type": "duration", "number": 3, "unit": "working_days"},
        {"type": "enum", "value": "full_cover"},
        {"type": "categories", "values": ["extra_taxi", "extra_towing"]},
        {"type": "text", "text": "short note"},
        {"type": "not_stated"},
    ],
)
def test_schema_value_accepts_each_type(value: dict[str, Any]) -> None:
    TopicRatingOut.model_validate(_value(value))


def test_schema_other_valid_answer_passes() -> None:
    answer = other_answer("c1")
    answer["clauses"].append(other_finding_clause("c2"))
    assert len(OtherRatingOut.model_validate(answer).clauses) == 2


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.update(extra=1),
        lambda a: a["clauses"][0].update(extra=1),
        lambda a: a["clauses"][0].update(no_issue=False),  # no_issue false without a finding
        lambda a: a["clauses"][0].update(
            findings=[finding(attribute=None)]
        ),  # no_issue true with one
        lambda a: a["clauses"].append(
            {"clause": "c9", "no_issue": False, "findings": [finding(attribute=None)] * 3}
        ),
        lambda a: a["clauses"].extend(other_answer(*[f"c{i}" for i in range(4, 46)])["clauses"]),
        lambda a: a["clauses"][0].update(clause="clause 1"),
    ],
)
def test_schema_other_refuses_bad_shapes(change: Any) -> None:
    answer = copy.deepcopy(other_answer())
    change(answer)
    with pytest.raises(ValidationError):
        OtherRatingOut.model_validate(answer)


def test_schema_other_accepts_two_findings_and_forty_clauses() -> None:
    answer = other_answer(*[f"c{i}" for i in range(1, 40)])
    answer["clauses"].append(
        {"clause": "c40", "no_issue": False, "findings": [finding(attribute=None)] * 2}
    )
    assert len(OtherRatingOut.model_validate(answer).clauses) == 40
