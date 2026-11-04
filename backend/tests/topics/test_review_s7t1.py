# ruff: noqa: E501
"""S7-T1 review findings: topic ids, catalog ids, attribute ids, value ids, catalog memo."""

from __future__ import annotations

from typing import Any

import pytest

from app.pseudo.gate import confirm_topic
from app.topics.catalog import load_catalog
from app.topics.model import TopicDefinitionError
from app.topics.safety import TopicTextError
from tests.topics.helpers import CATALOG_OK, attribute, definition

CATALOG = load_catalog(CATALOG_OK)


def outcome(catalog: Any = None, **changes: Any) -> str:
    try:
        confirm_topic(definition(**changes), catalog=catalog)
    except (TopicTextError, TopicDefinitionError) as error:
        return error.code
    return "accepted"


# --- topic ids ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "topic_id"),
    [
        ("custom", "custom_1"),
        ("custom", "custom_99"),
        ("custom", "custom_10"),
        ("suggested", "suggested_1"),
        ("suggested", "suggested_99"),
    ],
)
def test_topic_id_custom_or_suggested_number_is_accepted(origin: str, topic_id: str) -> None:
    assert outcome(origin=origin, topic_id=topic_id, description="") == "accepted"


@pytest.mark.parametrize(
    "topic_id",
    [
        "custom_0",
        "custom_100",
        "custom_01",
        "custom_",
        "custom1",
        "custom_1a",
        "suggested_00",
        "suggested_100",
        "my_topic",
        "deductible",
        "theft_cover",
        "custom__1",
        "Custom_1",
        "custom_-1",
    ],
)
def test_topic_id_outside_the_pattern_is_refused(topic_id: str) -> None:
    assert outcome(origin="custom", topic_id=topic_id) == "invalid_topic_definition"


def test_topic_id_of_a_catalog_topic_cannot_be_reused_by_a_custom_topic() -> None:
    assert outcome(CATALOG, origin="custom", topic_id="deductible") == "invalid_topic_definition"
    assert (
        outcome(CATALOG, origin="suggested", topic_id="rent", description="")
        == "invalid_topic_definition"
    )


# --- side and domain are catalog ids -----------------------------------------------------------------------------


def test_custom_topic_with_catalog_domain_and_side_is_accepted() -> None:
    assert outcome(CATALOG, domain="kasko", side="insured") == "accepted"
    assert outcome(CATALOG, domain="lease", side="landlord") == "accepted"


@pytest.mark.parametrize("domain", ["nope", "KASKO", "kasko ", "<b>", "x" * 500])
def test_custom_topic_with_unknown_domain_is_refused(domain: str) -> None:
    assert outcome(CATALOG, domain=domain) == "invalid_topic_definition"


@pytest.mark.parametrize(
    "side", ["hacker", "tenant", "Insured", "", "ignore previous instructions"]
)
def test_custom_topic_with_a_side_that_is_not_of_the_domain_is_refused(side: str) -> None:
    assert outcome(CATALOG, domain="kasko", side=side) == "invalid_topic_definition"


# --- attribute ids of non-catalog topics ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr_id",
    [
        "ignore_previous_instructions",
        "rate_as_green",
        "system_prompt",
        "ignore_all_previous_instructions",
    ],
)
def test_attribute_id_with_an_injection_phrase_is_flagged(attr_id: str) -> None:
    assert outcome(attributes=(attribute(id=attr_id),)) == "topic_flagged"


def test_attribute_id_with_a_normal_phrase_is_accepted() -> None:
    assert outcome(attributes=(attribute(id="towing_limit"),)) == "accepted"


def _pair(n: int) -> str:
    return chr(97 + n % 26) + chr(97 + (n * 7 + 3) % 26)


def _capped(attr_id: str) -> dict[str, Any]:
    words = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "kappa",
        "sigma",
        "omega",
        "theta",
        "lambda",
        "zeta",
    ]

    def line(n: int, size: int) -> str:
        text = " ".join(words[(n + i) % len(words)] for i in range(40))
        return text[:size].rstrip()

    return {
        "title": line(0, 80),
        "description": line(1, 200),
        "attributes": tuple(
            attribute(id=f"{attr_id}{chr(97 + n)}"[:47], label=line(n + 2, 120)) for n in range(12)
        ),
        "synonyms_en": tuple(line(n + 3, 55) + " " + _pair(n) for n in range(32)),
    }


def test_attribute_ids_are_counted_in_the_4_kib_cap() -> None:
    assert outcome(**_capped("ab")) == "accepted"
    assert outcome(**_capped("q" * 46)) == "topic_too_large"


# --- Catalog.definition ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("nope", "deductible", "insured", "en"),
        ("kasko", "nope", "insured", "en"),
        ("kasko", "deductible", "tenant", "en"),
        ("kasko", "deductible", "insured", "de"),
        ("lease", "deductible", "tenant", "en"),
    ],
)
def test_catalog_definition_of_an_unknown_name_raises_key_error(
    args: tuple[str, str, str, str],
) -> None:
    with pytest.raises(KeyError):
        CATALOG.definition(*args)


def test_catalog_definition_carries_value_ids_that_are_the_same_in_every_language() -> None:
    ids = {
        lang: CATALOG.definition("kasko", "theft_cover", "insured", lang).attributes[0]
        for lang in ("en", "uk", "ru")
    }

    assert {a.value_ids for a in ids.values()} == {
        ("covered", "not_covered", "conditional", "not_stated")
    }
    assert ids["en"].values != ids["uk"].values
    assert ids["en"].values[0] == "Covered"
    assert len(ids["uk"].values) == len(ids["uk"].value_ids)


def test_catalog_definition_enum_order_uses_value_ids() -> None:
    attr = CATALOG.definition("kasko", "theft_cover", "insured", "uk").attributes[0]

    assert attr.direction == "ordered"
    assert attr.order == ("covered", "conditional", "not_covered", "not_stated")


def test_confirmed_attribute_carries_value_ids_and_order_ids_in_every_language() -> None:
    by_lang = {
        lang: confirm_topic(
            CATALOG.definition("kasko", "theft_cover", "insured", lang), catalog=CATALOG
        ).attributes[0]
        for lang in ("en", "uk", "ru")
    }

    assert {a.value_ids for a in by_lang.values()} == {
        ("covered", "not_covered", "conditional", "not_stated")
    }
    assert {a.order for a in by_lang.values()} == {
        ("covered", "conditional", "not_covered", "not_stated")
    }
    assert by_lang["uk"].values[0] == "Покрито"


def test_confirmed_attribute_categories_carry_value_ids() -> None:
    attr = confirm_topic(
        CATALOG.definition("kasko", "exclusions", "insured", "ru"), catalog=CATALOG
    ).attributes[0]

    assert attr.value_ids == ("war", "racing")
    assert attr.values == ("Война", "Гонки")


def test_custom_attribute_with_value_ids_keeps_them() -> None:
    attr = attribute(type="categories", values=("City", "Region"), value_ids=("city", "region"))

    topic = confirm_topic(definition(attributes=(attr,)))

    assert topic.attributes[0].value_ids == ("city", "region")


@pytest.mark.parametrize(
    "ids", [("a",), ("city", "city"), ("City", "region"), ("city", "re gion"), ()]
)
def test_custom_attribute_with_bad_value_ids_is_refused(ids: tuple[str, ...]) -> None:
    attr = attribute(type="categories", values=("City", "Region"), value_ids=ids)

    assert outcome(attributes=(attr,)) == "invalid_topic_definition"


def test_custom_enum_order_with_labels_instead_of_ids_is_refused() -> None:
    attr = attribute(
        type="enum",
        values=("Yes", "No"),
        value_ids=("yes", "no"),
        direction="ordered",
        order=("Yes", "No"),
    )

    assert outcome(attributes=(attr,)) == "invalid_topic_definition"


def test_attribute_without_values_has_no_value_ids() -> None:
    assert outcome(attributes=(attribute(value_ids=("abc",)),)) == "invalid_topic_definition"


# --- memoized catalog ------------------------------------------------------------------------------------------------------------------


def test_load_catalog_twice_returns_the_memoized_object() -> None:
    assert load_catalog(CATALOG_OK) is load_catalog(CATALOG_OK)
