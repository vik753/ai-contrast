"""S9-T2 AC1: rate_other answers every clause of the batch."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.port import OutputLanguage
from app.analysis.rate import rate_other
from app.analysis.schemas import BadOutputError

from .helpers import (
    FakeProvider,
    doc,
    ev,
    failure,
    finding,
    other_answer,
    other_finding_clause,
    run,
)

EN = OutputLanguage.EN


def test_rate_other_every_clause_answered_returns_typed_result() -> None:
    answer = other_answer("c1", "c3")
    answer["clauses"].insert(1, other_finding_clause("c2"))

    result = run(rate_other(FakeProvider(answer), doc(), language=EN))

    assert [c.clause for c in result.clauses] == ["c1", "c2", "c3"]
    assert result.clauses[1].findings[0].rating == "yellow"


@pytest.mark.parametrize(
    "answer",
    [
        other_answer("c1", "c2"),  # c3 missing
        other_answer("c1", "c2", "c3", "c4"),  # unknown id
        other_answer("c1", "c2", "c3", "c2"),  # answered twice
    ],
    ids=["missing_clause", "unknown_clause", "duplicate_clause"],
)
def test_rate_other_missing_unknown_or_repeated_clause_is_bad_output(
    answer: dict[str, Any],
) -> None:
    provider = FakeProvider(answer)

    assert isinstance(failure(rate_other(provider, doc(), language=EN)), BadOutputError)
    assert len(provider.requests) == 2


def test_rate_other_empty_answer_is_bad_output() -> None:
    provider = FakeProvider({"clauses": []})

    assert isinstance(failure(rate_other(provider, doc(), language=EN)), BadOutputError)


def test_rate_other_finding_with_an_attribute_is_bad_output() -> None:
    answer = other_answer("c1", "c3")
    answer["clauses"].append(
        {"clause": "c2", "no_issue": False, "findings": [finding(evidence=[ev("c2", "pays")])]}
    )

    assert isinstance(failure(rate_other(FakeProvider(answer), doc(), language=EN)), BadOutputError)


def test_rate_other_finding_with_unknown_evidence_clause_is_bad_output() -> None:
    answer = other_answer("c1", "c3")
    answer["clauses"].append(other_finding_clause("c2"))
    answer["clauses"][-1]["findings"][0]["evidence"] = [ev("c8", "x")]

    assert isinstance(failure(rate_other(FakeProvider(answer), doc(), language=EN)), BadOutputError)


def test_rate_other_sends_one_document_and_no_topic() -> None:
    provider = FakeProvider(other_answer())
    document = doc()

    run(rate_other(provider, document, language=EN))

    assert provider.requests[0].document is document
    assert provider.requests[0].topic is None
    assert provider.requests[0].text is None
