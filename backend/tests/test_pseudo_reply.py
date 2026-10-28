# ruff: noqa: RUF001, RUF003, PT018
"""S5b-T1 AC3: reply fields, neutralization, matching view, boundary snapping
(ADR 0015 points 1-2).
"""

from __future__ import annotations

import itertools
import unicodedata
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import (
    EDRPOU,
    IBAN,
    IBAN_SPACED,
    clause_warning_codes,
    covering,
    detect,
    detect_blocks,
    entities_of,
    entity_strings,
    span_text,
)
from tests.segment_helpers import block

Make = Callable[..., TestClient]
CLASSES = {
    "ORG", "PERSON", "TAX_ID", "ACCOUNT", "ADDRESS", "PHONE", "EMAIL", "URL",
    "PERSONAL_DOC", "DOC_NO", "VEHICLE", "SIGNATURE", "HEALTH",
}  # fmt: skip

SAMPLE = [
    "Страхова компанія ТОВ «Альфа Тест» (далі — Страховик), код ЄДРПОУ " + EDRPOU + ".",
    "Пишіть на ivan.test@example.com, тел. +380 44 123 45 67.",
]


def test_reply_has_detector_version_string_and_original_fields(make_client: Make) -> None:
    data = detect(make_client(), *SAMPLE)

    assert set(data) >= {
        "clauses", "blocks", "removed", "warnings",
        "detector_version", "entities", "requisites", "neutralized",
    }  # fmt: skip
    assert isinstance(data["detector_version"], str) and data["detector_version"]


def test_reply_detector_version_is_stable_between_calls(make_client: Make) -> None:
    client = make_client()

    assert (
        detect(client, *SAMPLE)["detector_version"] == detect(client, "Текст.")["detector_version"]
    )


def test_reply_entity_shape_has_id_class_precision_spans_and_no_value(make_client: Make) -> None:
    data = detect(make_client(), *SAMPLE)

    assert data["entities"]
    for entity in data["entities"]:
        assert set(entity) == {"id", "class", "precision", "spans"}
        assert entity["class"] in CLASSES
        assert entity["precision"] in ("high", "normal")
        assert entity["spans"]
        for span in entity["spans"]:
            assert len(span) == 3 and all(isinstance(n, int) for n in span)
            b, s, e = span
            assert 0 <= b < len(data["blocks"]) and 0 <= s < e <= len(data["blocks"][b]["text"])


def test_reply_entity_ids_are_unique_e_numbers(make_client: Make) -> None:
    data = detect(make_client(), *SAMPLE)

    ids = [e["id"] for e in data["entities"]]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("e") and i[1:].isdigit() for i in ids)


def test_reply_contains_no_value_strings_outside_the_blocks(make_client: Make) -> None:
    data = detect(make_client(), *SAMPLE)
    stripped = dict(data)
    del stripped["blocks"]

    text = str(stripped)
    for value in ("ivan.test@example.com", EDRPOU, "Альфа Тест", "+380 44 123 45 67"):
        assert value not in text


def test_reply_entity_spans_are_not_overlapping_between_entities(make_client: Make) -> None:
    data = detect(make_client(), *SAMPLE)

    spans = sorted(tuple(sp) for e in data["entities"] for sp in e["spans"])
    for (b1, _, e1), (b2, s2, _) in itertools.pairwise(spans):
        assert b1 != b2 or e1 <= s2


def test_reply_entity_spans_of_one_entity_are_in_document_order(make_client: Make) -> None:
    data = detect(make_client(), "Пишіть a.b@example.com.", "Копія a.b@example.com.")

    [entity] = entities_of(data, "EMAIL")
    assert entity["spans"] == sorted(entity["spans"])


def test_reply_masks_point_into_returned_cleaned_blocks_after_cleaning(make_client: Make) -> None:
    data = detect(make_client(), "Пишіть\u200b на ivan.test\u200b@example.com щодо.")

    assert covering(data, "ivan.test@example.com", {"EMAIL"})
    assert "\u200b" not in data["blocks"][0]["text"]


# -------------------------------------------------------------- neutralized


@pytest.mark.parametrize("literal", ["[ORG_2]", "[A.PERSON_1]", "[B.ACCOUNT_17]"])
def test_neutralize_placeholder_lookalike_brackets_become_math_brackets(
    make_client: Make, literal: str
) -> None:
    text = f"1. Платіж на {literal} сплачується вчасно."

    data = detect(make_client(), text)

    returned = data["blocks"][0]["text"]
    assert literal not in returned
    assert returned == text.replace("[", "⟦").replace("]", "⟧")
    assert len(returned) == len(text)
    assert data["neutralized"], data["neutralized"]


def test_neutralize_reports_span_of_each_lookalike_in_cleaned_blocks(make_client: Make) -> None:
    text = "1. Платіж на [ORG_2] і на [A.PERSON_1] сплачується."

    data = detect(make_client(), text)

    texts = sorted(span_text(data, sp) for sp in data["neutralized"])
    assert len(texts) == 2
    assert texts[0].startswith("⟦") and texts[0].endswith("⟧")
    assert any("ORG_2" in t for t in texts) and any("PERSON_1" in t for t in texts)


def test_neutralize_adds_placeholder_lookalike_clause_warning(make_client: Make) -> None:
    data = detect(make_client(), "1. Платіж на [ORG_2] сплачується.", "2. Інший пункт.")

    warnings = [w for w in data["warnings"] if w["code"] == "placeholder_lookalike"]
    assert len(warnings) == 1
    assert warnings[0]["clause"] == data["clauses"][0]["id"]


def test_neutralize_lookalike_on_confusable_skeleton_is_found(make_client: Make) -> None:
    # Cyrillic О in ORG, Latin letters mixed; the skeleton equals [ORG_2].
    text = "1. Платіж на [ОRG_2] сплачується."

    data = detect(make_client(), text)

    assert data["blocks"][0]["text"] == text.replace("[", "⟦").replace("]", "⟧")
    assert any(w["code"] == "placeholder_lookalike" for w in data["warnings"])


def test_neutralize_fullwidth_brackets_lookalike_is_found(make_client: Make) -> None:
    text = "1. Платіж на ［ORG_2］ сплачується."

    data = detect(make_client(), text)

    assert any(w["code"] == "placeholder_lookalike" for w in data["warnings"])
    assert "［ORG_2］" not in data["blocks"][0]["text"]
    assert len(data["blocks"][0]["text"]) == len(text)


def test_neutralize_ordinary_square_brackets_are_kept(make_client: Make) -> None:
    text = "1. Див. додаток [1] та пункт [a] цього договору."

    data = detect(make_client(), text)

    assert data["blocks"][0]["text"] == text
    assert data["neutralized"] == []
    assert not any(w["code"] == "placeholder_lookalike" for w in data["warnings"])


# --------------------------------------------------- masked next to amount


def test_warning_masked_next_to_amount_when_entity_touches_an_amount(make_client: Make) -> None:
    data = detect(
        make_client(), "1. Виплата ТОВ «Альфа Тест» 5 000 грн здійснюється вчасно.", "2. Інше."
    )

    warnings = [w for w in data["warnings"] if w["code"] == "masked_next_to_amount"]
    assert [w["clause"] for w in warnings] == [data["clauses"][0]["id"]]


def test_warning_masked_next_to_amount_absent_when_amount_is_far_away(make_client: Make) -> None:
    far = "Страховик здійснює виплату у встановленому порядку та в погоджені строки без затримок"
    data = detect(
        make_client(), f"1. ТОВ «Альфа Тест» {far} і лише потім сума становить 5 000 грн."
    )

    assert "masked_next_to_amount" not in clause_warning_codes(data)


def test_warning_masked_next_to_amount_absent_without_entity(make_client: Make) -> None:
    data = detect(make_client(), "1. Страховик сплачує 5 000 грн протягом 30 днів.")

    assert "masked_next_to_amount" not in clause_warning_codes(data)


# ------------------------------------------------------- matching view


def test_matching_hyphen_split_at_line_end_is_masked_as_one_value(make_client: Make) -> None:
    data = detect(make_client(), "Пишіть на ivan.test@exam-\nple.com щодо договору.")

    entities = covering(data, "ivan.test@exam", {"EMAIL"})
    assert entities
    assert "ple.com" in "".join(entity_strings(data, entities[0]))


def test_matching_hyphen_split_name_in_two_blocks_is_covered(make_client: Make) -> None:
    data = detect_blocks(
        make_client(), [block("Страхова компанія ТОВ «Аль-"), block("фа Тест» надає послуги.")]
    )

    assert entities_of(data, "ORG")


def test_matching_homoglyph_latin_in_cyrillic_email_is_masked(make_client: Make) -> None:
    # Latin P (U+0050) replaces Cyrillic Р in the keyword.
    data = detect(make_client(), "Код ЄДPПОУ " + EDRPOU + " вказано.")

    assert covering(data, EDRPOU, {"TAX_ID"})


def test_matching_homoglyph_context_keyword_still_gives_high(make_client: Make) -> None:
    # Latin "I", "B", "A", "N" mixed with Cyrillic "В" in IBAN context.
    data = detect(make_client(), "IВAN " + IBAN + " відкрито.")

    assert [e["precision"] for e in covering(data, IBAN, {"ACCOUNT"})] == ["high"]


def test_matching_homoglyph_in_legal_form_still_finds_quoted_name(make_client: Make) -> None:
    # Latin T and O in "ТОВ" (U+0054 U+004F) instead of Cyrillic.
    data = detect(make_client(), "Компанія TOВ «Альфа Тест» надає послуги.")

    assert covering(data, "Альфа Тест", {"ORG"})


def test_matching_digit_lookalike_letters_in_iban_are_still_masked(make_client: Make) -> None:
    value = IBAN_SPACED.replace("0", "О", 1) if "0" in IBAN_SPACED else IBAN_SPACED
    data = detect(make_client(), f"IBAN {value} відкрито.")

    assert [e for e in data["entities"] if e["class"] == "ACCOUNT"]


def test_matching_nfkc_fullwidth_digits_are_masked_over_whole_source_characters(
    make_client: Make,
) -> None:
    fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in EDRPOU)
    text = f"Код ЄДРПОУ {fullwidth} вказано."

    data = detect(make_client(), text)

    [entity] = covering(data, fullwidth, {"TAX_ID"})
    assert "".join(entity_strings(data, entity)) == fullwidth


def test_matching_expanded_character_before_value_keeps_spans_on_source_characters(
    make_client: Make,
) -> None:
    # U+2116 expands to "No" under NFKC; the document number follows it.
    text = "Договір \u211645/2024-К від першого лютого."
    assert unicodedata.normalize("NFKC", "\u2116") == "No"

    data = detect(make_client(), text)

    assert covering(data, "45/2024-К", {"DOC_NO"})
    for entity in data["entities"]:
        for sp in entity["spans"]:
            assert span_text(data, sp) in text


def test_matching_spans_always_land_on_source_character_boundaries(make_client: Make) -> None:
    text = "Тел. ＋380 44 123 45 67 і ｉｖａｎ＠example.com ㎜ ǆ."

    data = detect(make_client(), text)

    for entity in data["entities"]:
        for b, s, e in entity["spans"]:
            assert 0 <= s < e <= len(data["blocks"][b]["text"])
            assert span_text(data, (b, s, e)) == data["blocks"][b]["text"][s:e]


def test_matching_returned_blocks_keep_source_text_not_the_matching_view(make_client: Make) -> None:
    text = "Код ЄДРПОУ ＿ " + "".join(chr(ord(c) + 0xFEE0) for c in EDRPOU) + " вказано."

    data = detect(make_client(), text)

    assert "".join(chr(ord(c) + 0xFEE0) for c in EDRPOU) in data["blocks"][0]["text"]


def _spans(data: dict[str, Any]) -> list[Any]:
    return [sp for e in data["entities"] for sp in e["spans"]]


def test_matching_zero_width_split_value_is_masked_after_cleaning(make_client: Make) -> None:
    split = EDRPOU[:4] + "\u200b" + EDRPOU[4:]

    data = detect(make_client(), f"Код ЄДРПОУ {split} вказано.")

    assert covering(data, EDRPOU, {"TAX_ID"})
    assert _spans(data)
