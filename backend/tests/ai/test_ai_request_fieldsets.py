"""S7-T1 AC5: per-template field sets of ``AIRequest`` (ADR 0017 point 5)."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

import pytest

from app.ai.port import AIRequest
from app.ai.prompts import PromptTemplate
from app.pseudo import gate
from app.pseudo.gate import PseudonymizedText, document_digest
from tests.ai.helpers import Verdict, first_template, make_document
from tests.topics.helpers import confirmed

DOC_TEMPLATE = ("SUGGEST_TOPICS",)
TOPIC_TEMPLATES = ("PROPOSE_ATTRIBUTES", "EXPAND_SYNONYMS")
BAD = (TypeError, ValueError)


def build(template: PromptTemplate, **fields: Any) -> AIRequest:
    return AIRequest(template=template, schema=Verdict, max_tokens=256, **fields)


def a_text(document: Any) -> PseudonymizedText:
    return PseudonymizedText("some text", document_digest(document), gate._SENTINEL)  # type: ignore[call-arg]


def test_prompt_templates_include_the_three_topic_members() -> None:
    names = {t.name for t in PromptTemplate}

    assert {"SUGGEST_TOPICS", "PROPOSE_ATTRIBUTES", "EXPAND_SYNONYMS"} <= names


def test_prompt_templates_have_distinct_non_empty_instruction_texts() -> None:
    values = [t.value for t in PromptTemplate]

    assert all(isinstance(v, str) and v for v in values)
    assert len(set(values)) == len(values)


# --- SUGGEST_TOPICS: document required, topic and text forbidden --------------------------------------------


def test_suggest_topics_with_a_document_is_accepted() -> None:
    request = build(PromptTemplate.SUGGEST_TOPICS, document=make_document())

    assert request.topic is None
    assert request.text is None


def test_suggest_topics_without_a_document_is_refused() -> None:
    with pytest.raises(BAD):
        build(PromptTemplate.SUGGEST_TOPICS)


def test_suggest_topics_with_a_topic_is_refused() -> None:
    with pytest.raises(BAD):
        build(PromptTemplate.SUGGEST_TOPICS, document=make_document(), topic=confirmed())


def test_suggest_topics_with_a_text_is_refused() -> None:
    document = make_document()

    with pytest.raises(BAD):
        build(PromptTemplate.SUGGEST_TOPICS, document=document, text=a_text(document))


# --- PROPOSE_ATTRIBUTES and EXPAND_SYNONYMS: topic required, document and text forbidden -----------------------


@pytest.mark.parametrize("name", TOPIC_TEMPLATES)
def test_topic_template_with_a_topic_only_is_accepted(name: str) -> None:
    request = build(PromptTemplate[name], topic=confirmed())

    assert request.document is None
    assert request.text is None


@pytest.mark.parametrize("name", TOPIC_TEMPLATES)
def test_topic_template_without_a_topic_is_refused(name: str) -> None:
    with pytest.raises(BAD):
        build(PromptTemplate[name])


@pytest.mark.parametrize("name", TOPIC_TEMPLATES)
def test_topic_template_with_a_document_is_refused(name: str) -> None:
    with pytest.raises(BAD):
        build(PromptTemplate[name], topic=confirmed(), document=make_document())


@pytest.mark.parametrize("name", TOPIC_TEMPLATES)
def test_topic_template_with_a_text_is_refused(name: str) -> None:
    document = make_document()

    with pytest.raises(BAD):
        build(PromptTemplate[name], topic=confirmed(), text=a_text(document))


@pytest.mark.parametrize("name", TOPIC_TEMPLATES)
@pytest.mark.parametrize("topic", ["Roadside assistance", b"x", ("a",), {"title": "x"}])
def test_topic_template_with_a_topic_that_is_not_a_gate_object_is_refused(
    name: str, topic: object
) -> None:
    with pytest.raises(BAD):
        build(PromptTemplate[name], topic=topic)


# --- existing template unchanged --------------------------------------------------------------------------------


def test_document_template_still_requires_a_document() -> None:
    with pytest.raises(TypeError):
        build(first_template())
    with pytest.raises(TypeError):
        build(first_template(), document=None)


def test_document_template_still_accepts_document_with_optional_topic_and_text() -> None:
    document = make_document()

    plain = build(first_template(), document=document)
    full = build(first_template(), document=document, topic=confirmed(), text=a_text(document))

    assert plain.topic is None
    assert plain.text is None
    assert full.topic is not None
    assert full.text is not None


def test_document_template_text_of_another_document_is_still_refused() -> None:
    other = make_document("A different clause.", label="B")

    with pytest.raises(ValueError, match=r"."):
        build(first_template(), document=make_document(), text=a_text(other))


def test_first_prompt_template_is_still_the_document_template() -> None:
    assert first_template().name == "DOCUMENT_JSON"
