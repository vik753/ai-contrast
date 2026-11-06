"""S8-T2 unit tests of the developer: batches, schemas, analysis pass table, gate subset,
tagging request and the template schemas."""

from __future__ import annotations

import json

import pytest

from app.ai.port import AIRequest, TaggingRequest
from app.ai.prompting import build_messages
from app.ai.prompts import PromptTemplate
from app.limits.analysis_pass import MAX_CHARS, AnalysisPasses
from app.limits.free_pass import FreePassError
from app.pseudo.gate import confirm_topic, subset_document
from app.tagging.batches import MAX_BATCH_CHARS, plan_batches, tag_max_tokens, worst_case
from app.tagging.schemas import (
    BadOutputError,
    CheckOut,
    TagOut,
    checked_answers,
    checked_tags,
)
from app.topics.model import TopicDefinition
from tests.ai.helpers import make_document


def _topic(n: int = 1):  # noqa: ANN202
    definition = TopicDefinition(
        origin="custom",
        domain="kasko",
        topic_id=f"custom_{n}",
        title="Deductible handling",
        description="Rules of the subject",
        side="insured",
    )
    return confirm_topic(definition)


def test_plan_batches_respects_clause_and_character_caps() -> None:
    assert plan_batches([]) == []
    assert plan_batches([10] * 41) == [(0, 40), (40, 41)]
    assert plan_batches([MAX_BATCH_CHARS, 1]) == [(0, 1), (1, 2)]
    assert plan_batches([20_000, 20_000]) == [(0, 1), (1, 2)]


def test_worst_case_counts_four_calls_per_batch_and_grows_with_text() -> None:
    topics = (_topic(),)
    small = worst_case([(0, 1)], [100], topics)
    big = worst_case([(0, 1)], [10_000], topics)
    assert small[0] == big[0] == 4
    assert big[1] > small[1] > 0
    assert tag_max_tokens(40) <= 4096


def test_checked_tags_rejects_unknown_clause_index_and_repeats() -> None:
    def parse(data: object) -> object:
        return checked_tags(TagOut.model_validate(data), {"c1", "c2"}, 2)

    good = {"tags": [{"clause": "c1", "topics": [{"index": "T1", "confidence": "high"}]}]}
    assert parse(good) == ({"c1": {1}}, {})
    for bad in (
        {"tags": [{"clause": "c9", "topics": []}]},
        {"tags": [{"clause": "c1", "topics": [{"index": "T3", "confidence": "low"}]}]},
        {"tags": [{"clause": "c1", "topics": []}, {"clause": "c1", "topics": []}]},
    ):
        with pytest.raises(BadOutputError):
            parse(bad)


def test_checked_answers_only_asked_pairs() -> None:
    asked = [("c1", 1), ("c2", 2)]
    out = CheckOut.model_validate({"answers": [{"clause": "c1", "topic": "T1", "regulates": True}]})
    assert checked_answers(out, asked) == {("c1", 1)}
    unasked = CheckOut.model_validate(
        {"answers": [{"clause": "c1", "topic": "T2", "regulates": True}]}
    )
    with pytest.raises(BadOutputError):
        checked_answers(unasked, asked)


@pytest.mark.parametrize(
    ("template", "schema"),
    [(PromptTemplate.TAG_CLAUSES, TagOut), (PromptTemplate.CHECK_TAGS, CheckOut)],
)
def test_template_schema_names_match_the_pydantic_schema(
    template: PromptTemplate, schema: type
) -> None:
    text = template.value
    embedded = json.loads(text[text.index("JSON schema of the answer:\n") + 27 :])
    real = schema.model_json_schema()

    def names(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    found |= set(value)
                found |= names(value)
        elif isinstance(node, list):
            for value in node:
                found |= names(value)
        return found

    assert names(embedded) == names(real)


def test_subset_document_keeps_order_and_refuses_unknown_ids() -> None:
    document = make_document("a one", "b two", "c three")
    sub = subset_document(document, ["c3", "c1"])
    assert [c.id for c in sub.clauses] == ["c1", "c3"]
    with pytest.raises(ValueError):  # noqa: PT011
        subset_document(document, ["c9"])
    with pytest.raises(ValueError):  # noqa: PT011
        subset_document(document, ["c1", "c1"])


def test_tagging_request_rules() -> None:
    document = make_document("a one", "b two")
    topics = (_topic(1), _topic(2))
    with pytest.raises(TypeError):
        AIRequest(PromptTemplate.TAG_CLAUSES, TagOut, 100, document=document)
    with pytest.raises(TypeError):
        TaggingRequest(PromptTemplate.TAG_CLAUSES, TagOut, 100, document=document)  # no topics
    with pytest.raises(ValueError):  # noqa: PT011
        TaggingRequest(
            PromptTemplate.CHECK_TAGS,
            CheckOut,
            100,
            document=document,
            topics=topics,
            pairs=((5, 1),),
        )
    request = TaggingRequest(
        PromptTemplate.CHECK_TAGS,
        CheckOut,
        100,
        document=document,
        topics=topics,
        pairs=((1, 2),),
        topic_numbers=(2,),
    )
    users = "\n".join(m.content for m in build_messages(request) if m.role == "user")
    assert "c2 T2" in users
    assert "T1:" not in users
    assert "T2: Deductible handling - Rules of the subject" in users


def _passes(max_calls: int = 10, max_neurons: int = 100) -> tuple[AnalysisPasses, list[float]]:
    now = [1_000_000.0]
    return AnalysisPasses(5, max_calls, max_neurons, lambda: now[0]), now


def test_analysis_pass_caps_documents_and_sizes() -> None:
    passes, _ = _passes()
    issued = passes.issue("client")
    assert issued is not None
    value, nonce = issued
    assert passes.lookup(value, "client")[0] == nonce
    assert passes.fits(nonce, 10, 100)
    assert not passes.fits(nonce, 11, 1)
    assert not passes.fits(nonce, 1, 101)
    passes.reserve(nonce, 4, 40, "d1", 1000)
    passes.reserve(nonce, 4, 40, "d2", 1000)
    assert not passes.fits(nonce, 4, 1)
    passes.settle(nonce, (8, 2), (80, 5))
    assert passes.fits(nonce, 8, 90)
    assert passes.size_error(nonce, "d3", 10) == "too_many_documents"
    assert passes.size_error(nonce, "d1", 1000) is None
    assert passes.size_error(nonce, "d1", MAX_CHARS) == "free_too_large"


def test_analysis_pass_codes_and_audience() -> None:
    passes, now = _passes()
    value, _ = passes.issue("client") or ("", "")
    with pytest.raises(FreePassError) as invalid:
        passes.lookup(value.replace(".analysis.", ".topics."), "client")
    assert invalid.value.code == "analysis_pass_invalid"
    now[0] += 1801
    with pytest.raises(FreePassError) as expired:
        passes.lookup(value, "client")
    assert expired.value.code == "analysis_pass_expired"
