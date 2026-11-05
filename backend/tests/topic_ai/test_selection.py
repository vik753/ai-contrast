"""S7-T2 AC3a: catalog topics by id + version, caps per request, confirm_topic with catalog."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.topics.catalog import load_catalog
from app.topics.model import TopicDefinition, TopicDefinitionError
from app.topics.selection import CatalogRef, TopicSelection, TopicSelectionError, resolve_topics
from tests.topics.helpers import CATALOG_OK

CATALOG = load_catalog(CATALOG_OK)
APP = Path(__file__).resolve().parents[2] / "app"


def ref(**changes: str) -> CatalogRef:
    base = {
        "domain": "kasko",
        "topic_id": "deductible",
        "side": "insured",
        "lang": "en",
        "catalog_version": CATALOG.catalog_version,
    }
    return CatalogRef(**{**base, **changes})


def custom(n: int = 1, **changes: object) -> TopicDefinition:
    base = {
        "origin": "custom",
        "domain": "kasko",
        "topic_id": f"custom_{n}",
        "title": f"Own topic {chr(96 + n)}",
        "side": "insured",
    }
    return TopicDefinition(**{**base, **changes})


def test_catalog_topic_is_built_from_the_server_catalog_by_id() -> None:
    topics = resolve_topics(TopicSelection(catalog=[ref()]), CATALOG)
    expected = CATALOG.definition("kasko", "deductible", "insured", "en")
    assert topics[0].topic_id == "deductible"
    assert topics[0].title == expected.title
    assert [a.id for a in topics[0].attributes] == [a.id for a in expected.attributes]
    assert all(a.direction_source == "catalog" for a in topics[0].attributes)


def test_catalog_version_mismatch_is_refused() -> None:
    with pytest.raises(TopicSelectionError) as info:
        resolve_topics(TopicSelection(catalog=[ref(catalog_version="0" * 64)]), CATALOG)
    assert info.value.code == "catalog_version_mismatch"


def test_unknown_catalog_topic_is_refused() -> None:
    with pytest.raises(TopicSelectionError) as info:
        resolve_topics(TopicSelection(catalog=[ref(topic_id="nope_topic")]), CATALOG)
    assert info.value.code == "unknown_topic"


def test_catalog_origin_definition_in_the_custom_list_is_refused() -> None:
    fake = custom(origin="catalog", topic_id="deductible", title="Deductible")
    with pytest.raises(TopicDefinitionError) as info:
        resolve_topics(TopicSelection(custom=[fake]), CATALOG)
    assert info.value.code == "invalid_topic_definition"


def test_suggested_origin_definition_in_the_custom_list_is_refused() -> None:
    wrong = custom(origin="suggested", topic_id="suggested_1")
    with pytest.raises(TopicDefinitionError):
        resolve_topics(TopicSelection(custom=[wrong]), CATALOG)


def test_caps_30_catalog_10_suggested_10_custom_are_accepted() -> None:
    one = custom(1)
    sel = TopicSelection(
        catalog=[ref()] * 2,
        suggested=[custom(n, origin="suggested", topic_id=f"suggested_{n}") for n in range(1, 11)],
        custom=[custom(n) for n in range(1, 11)],
    )
    assert len(resolve_topics(sel, CATALOG)) == 22
    assert one


@pytest.mark.parametrize("which", ["catalog", "suggested", "custom"])
def test_one_over_the_cap_is_too_many_topics(which: str) -> None:
    sel = {
        "catalog": TopicSelection(catalog=[ref()] * 31),
        "suggested": TopicSelection(
            suggested=[custom(1, origin="suggested", topic_id=f"suggested_{n}") for n in range(11)]
        ),
        "custom": TopicSelection(custom=[custom(1)] * 11),
    }[which]
    with pytest.raises(TopicSelectionError) as info:
        resolve_topics(sel, CATALOG)
    assert info.value.code == "too_many_topics"


def test_every_confirm_topic_call_in_the_app_passes_the_catalog() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        if path.name == "gate.py" and path.parent.name == "pseudo":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name == "confirm_topic" and "catalog" not in {k.arg for k in node.keywords}:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
