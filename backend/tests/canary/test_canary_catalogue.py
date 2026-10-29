"""S5b-T4 AC 1: the canary set covers every ADR 0008 class, language and variant."""

from __future__ import annotations

import pytest

from tests.canary.catalogue import BY_ID, CANARIES, CLASSES

ADR_0008_CLASSES = {
    "ORG",
    "PERSON",
    "TAX_ID",
    "ACCOUNT",
    "ADDRESS",
    "PHONE",
    "EMAIL",
    "URL",
    "PERSONAL_DOC",
    "DOC_NO",
    "VEHICLE",
    "SIGNATURE",
    "HEALTH",
}


def test_catalogue_has_every_adr_0008_class() -> None:
    assert ADR_0008_CLASSES <= CLASSES


@pytest.mark.parametrize("cls", sorted(ADR_0008_CLASSES - {"PHONE", "URL"}))
def test_catalogue_has_every_class_in_ukrainian(cls: str) -> None:
    assert any(c.cls == cls and c.lang == "uk" for c in CANARIES)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_catalogue_has_many_classes_in_every_other_language(lang: str) -> None:
    assert len({c.cls for c in CANARIES if c.lang == lang}) >= 6


@pytest.mark.parametrize(
    "variant",
    [
        "uk-person-forms",  # case forms and initials, both orders
        "ru-person-forms",
        "uk-person-translit",  # Latin transliteration next to the Cyrillic name
        "uk-person-zero-width",
        "uk-person-soft-hyphen",
        "uk-person-line-end-hyphen",
        "uk-person-homoglyph",
        "uk-account-iban",  # with and without spaces
    ],
)
def test_catalogue_has_the_variant(variant: str) -> None:
    assert variant in BY_ID


def test_variant_texts_really_carry_the_variant() -> None:
    assert "\u200b" in BY_ID["uk-person-zero-width"].text
    assert "­" in BY_ID["uk-person-soft-hyphen"].text
    assert "-\n" in BY_ID["uk-person-line-end-hyphen"].text
    assert "e" in BY_ID["uk-person-homoglyph"].text.split("—")[1].split()[0]  # Latin e in Cyrillic
    assert any(ord(ch) < 0x80 for ch in BY_ID["uk-person-homoglyph"].text.split("—")[1].split()[0])


def test_needles_are_unique_across_canaries() -> None:
    seen: dict[str, str] = {}
    for canary in CANARIES:
        for needle in canary.needles:
            assert needle not in seen, f"{needle} in {canary.id} and {seen[needle]}"
            seen[needle] = canary.id
