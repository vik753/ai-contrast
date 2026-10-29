# ruff: noqa: RUF001
"""Detector round 2 (S5b-T4 follow-up): line breaks inside a block, English rules, sole
traders, names in a name context. Direct calls to ``detect``; synthetic values only."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.pseudo.detector import detect
from tests.pseudo_helpers import detect as detect_api
from tests.pseudo_helpers import span_text
from tests.segment_helpers import block, post_blocks

CPU_LIMIT_SECONDS = 20


def found(*blocks: str) -> list[tuple[str, str]]:
    """``(class, text)`` of every span of the detection, in document order."""
    result = detect(list(blocks), [])
    spans = [(b, s, e, entity.cls) for entity in result.entities for b, s, e in entity.spans]
    return [(cls, blocks[b][s:e]) for b, s, e, cls in sorted(spans)]


def texts(*blocks: str, cls: str | None = None) -> list[str]:
    return [t for c, t in found(*blocks) if cls is None or c == cls]


# ------------------------------------------------------------ 1 line breaks in a block


def test_wrap_keyword_split_from_its_value() -> None:
    assert texts("Рахунок Страховика: IBAN\nUA363052990000000026007233456", cls="ACCOUNT")


def test_wrap_card_split_across_lines() -> None:
    result = texts("Картка 4000 0012\n3456 7899 сплачена.", cls="ACCOUNT")
    assert result == ["4000 0012\n3456 7899"]


def test_wrap_iban_split_across_lines() -> None:
    result = texts("IBAN UA36 3052 9900\n0000 0026 0072 3345 6.", cls="ACCOUNT")
    assert result == ["UA36 3052 9900\n0000 0026 0072 3345 6"]


def test_wrap_rnokpp_on_the_line_after_an_address() -> None:
    result = texts(
        "Адреса: м. Львів, вул. Зелена, буд. 8, кв. 2.\nРНОКПП 31826 40979.", cls="TAX_ID"
    )
    assert result == ["31826 40979"]


def test_wrap_name_split_across_lines() -> None:
    assert texts("Страхувальник — Мирошниченко\nСвятослав Орестович.", cls="PERSON") == [
        "Мирошниченко\nСвятослав Орестович"
    ]


def test_wrap_blocks_stay_hard_boundaries() -> None:
    assert texts("IBAN UA36 3052 9900", "0000 0026 0072 3345 6", cls="ACCOUNT") == []


def test_wrap_address_does_not_swallow_the_next_sentence() -> None:
    result = texts("за адресою: [A.ADDRESS_1].\nКадастровий номер земельної ділянки.")
    assert "Кадастровий" not in " ".join(result)


@pytest.mark.parametrize("unit", ["a\n", "1\n"])
def test_wrap_one_million_characters_of_breaks_finish_within_the_cpu_limit(
    make_client: Callable[..., TestClient], unit: str
) -> None:
    text = (unit * 500_000)[:1_000_000]
    start = time.monotonic()

    response = post_blocks(make_client(), [block(text)])

    assert time.monotonic() - start < CPU_LIMIT_SECONDS + 5
    assert response.status_code in (200, 422), response.text[:100]


# ------------------------------------------------------------------ 2 English rules


def test_en_health_diagnosed_with_masks_the_condition() -> None:
    assert texts("Mary Smith has been diagnosed with type 2 diabetes.", cls="HEALTH") == [
        "type 2 diabetes"
    ]


def test_en_health_suffers_from() -> None:
    assert texts("The insured suffers from chronic asthma, and", cls="HEALTH") == ["chronic asthma"]


def test_en_health_medical_condition_needs_a_colon_or_of() -> None:
    assert texts("A pre-existing medical condition is excluded from cover.", cls="HEALTH") == []
    assert texts("Medical condition: epilepsy.", cls="HEALTH") == ["epilepsy"]
    assert texts("A medical condition of asthma, declared.", cls="HEALTH") == ["asthma"]


def test_en_insured_person_after_role_and_comma_is_a_name() -> None:
    assert texts("The insured, Gregory Pennington, signs.", cls="PERSON") == ["Gregory Pennington"]


def test_en_address_street_town_and_us_zip() -> None:
    assert texts("The office is at 221 Larkspur Lane, Springfield, IL 62704.", cls="ADDRESS") == [
        "221 Larkspur Lane, Springfield, IL 62704"
    ]


def test_en_address_uk_postcode_after_street() -> None:
    assert texts("Send it to 10 Downing Street, London SW1A 2AA today.", cls="ADDRESS") == [
        "10 Downing Street, London SW1A 2AA"
    ]


def test_en_address_uk_postcode_after_an_address_keyword() -> None:
    assert texts("Registered address: Flat 4, Maple House, Leeds LS1 4AP", cls="ADDRESS")


def test_en_address_ordinary_text_with_numbers_is_not_an_address() -> None:
    assert (
        texts("Payment within 5 Days at the Court of Appeal, 10 Percent more.", cls="ADDRESS") == []
    )


def test_en_passport_number_and_us_date_of_birth() -> None:
    result = texts("Passport No. 531847260, date of birth 04/17/1982.", cls="PERSONAL_DOC")
    assert result == ["531847260", "04/17/1982"]


@pytest.mark.parametrize(
    "line",
    [
        "DOB: 17 April 1982.",
        "Born on April 17, 1982 in Leeds.",
        "Date of birth 1982-04-17.",
        "The holder was born on 17th April 1982.",
    ],
)
def test_en_date_of_birth_forms(line: str) -> None:
    assert texts(line, cls="PERSONAL_DOC")


def test_en_date_without_birth_keyword_is_not_personal() -> None:
    assert texts("Signed on 04/17/1982 and on 17 April 1982.", cls="PERSONAL_DOC") == []


def test_en_vin_and_plate_with_keyword() -> None:
    result = texts("Vehicle VIN 2T1BR32E55C778899, registration plate KDL 4471.", cls="VEHICLE")
    assert result == ["2T1BR32E55C778899", "KDL 4471"]


@pytest.mark.parametrize("line", ["Reg. no. AB12 CDE.", "Number plate: AB12CDE.", "Plate A123 BCD"])
def test_en_uk_registration_plate_forms(line: str) -> None:
    assert texts(line, cls="VEHICLE")


def test_en_registration_without_a_plate_shape_is_not_a_vehicle() -> None:
    line = "Registration is valid for 5 years. Registration number 12345678."
    assert texts(line, cls="VEHICLE") == []


# -------------------------------------------------------------- 3 sole traders and names


def test_ru_individual_entrepreneur_long_form_is_org_and_person() -> None:
    result = found("Услуги оказывает индивидуальный предприниматель Захаров Валерий Кузьмич.")
    assert ("ORG", "индивидуальный предприниматель Захаров Валерий Кузьмич") in result
    assert ("PERSON", "Захаров Валерий Кузьмич") in result


def test_uk_individual_entrepreneur_long_form() -> None:
    result = found("Послуги надає індивідуальний підприємець Дорошенко Ярема Остапович.")
    assert ("PERSON", "Дорошенко Ярема Остапович") in result
    assert any(cls == "ORG" for cls, _ in result)


def test_ru_ip_short_form_still_works() -> None:
    assert ("PERSON", "Захаров В. К.") in found("ИП Захаров В. К. оказывает услуги.")


@pytest.mark.parametrize("patronymic", ["Ильич", "Кузьмич", "Фомич", "Лукич", "Никитич"])
def test_ru_masculine_patronymics_of_a_stems(patronymic: str) -> None:
    assert texts(f"Страхователь: Ковалевский Артём {patronymic}.", cls="PERSON")


def test_common_word_surnames_in_a_name_context() -> None:
    assert texts("Страхувальник: Мельник Олена Іванівна.", cls="PERSON") == [
        "Мельник Олена Іванівна"
    ]
    assert texts("Страхувальник — Коваль, що діє", cls="PERSON") == ["Коваль"]
    assert texts("Підписав Мельник І. І.", cls="PERSON") == ["Мельник І. І."]
    assert texts("Customer: Rose", cls="PERSON") == ["Rose"]
    assert texts("represented by Rose", cls="PERSON") == ["Rose"]
    assert texts("Виконавець ____ /Коваль/", cls="PERSON") == ["Коваль"]


def test_common_word_surnames_are_not_masked_as_ordinary_words() -> None:
    assert texts("Rose is a flower. Коваль працює у кузні. Мельник меле борошно.") == []
    assert texts("Customer: Yes. Insured: None. Buyer: Other.") == []


def test_role_then_organisation_is_not_a_person() -> None:
    assert texts("Замовник: ТОВ «Зорепад Інвест» діє.", cls="PERSON") == []
    assert texts("Customer: Acme Trading Ltd. pays.", cls="PERSON") == []


def test_double_surname_wrapped_at_its_own_hyphen_is_one_person(
    make_client: Callable[..., TestClient],
) -> None:
    data = detect_api(
        make_client(),
        "1. Страхувальник — Левченко-\nКравець Ілларіон Максимович (далі — Страхувальник).",
    )

    person = [e for e in data["entities"] if e["class"] == "PERSON"]
    covered = [span_text(data, sp) for e in person for sp in e["spans"]]
    assert any("Левченко" in t and "Кравець" in t for t in covered), covered


# ------------------------------------------------------------------ 4 tax id keyword gap


def test_rnokpp_with_a_space_and_a_role_word_after_the_keyword() -> None:
    assert texts("РНОКПП Виконавця: 31826 40979.", cls="TAX_ID") == ["31826 40979"]


# --------------------------------------------------- line-scoped rules stop at the break


def test_address_stops_at_a_break_before_a_clause_number() -> None:
    result = texts("Адреса: м. Київ, вул. Зелена, 12\n2.1. Страховик сплачує внесок.")
    assert result
    assert not any("2.1" in t or "Страховик" in t for t in result)


def test_address_stops_at_a_break_before_a_new_item_in_requisites() -> None:
    result = texts("Адреса: м. Київ, вул. Зелена, 12\nНеустойка за прострочення")
    assert result
    assert not any("Неустойка" in t for t in result)


def test_address_goes_on_over_a_wrap_after_a_comma_or_before_an_abbreviation() -> None:
    assert texts("Адреса: м. Київ, вул. Зелена,\nбуд. 8, кв. 2.", cls="ADDRESS") == [
        "м. Київ, вул. Зелена,\nбуд. 8, кв. 2"
    ]
    assert texts("Адреса: м. Київ, вул. Зелена\nбуд. 8, кв. 2.", cls="ADDRESS") == [
        "м. Київ, вул. Зелена\nбуд. 8, кв. 2"
    ]


def test_health_stops_at_a_break_before_a_new_item() -> None:
    assert texts("Діагноз: астма\nШтраф сплачується", cls="HEALTH") == ["астма"]


def test_signature_line_ends_at_its_break() -> None:
    assert not any("Next" in t for t in texts("____ /\nNext line /", cls="SIGNATURE"))


# --------------------------------------------------------------------- name forms


def test_en_contact_name_with_apostrophe_and_hyphen() -> None:
    assert texts("Contact: Mary O'Neil-Brown", cls="PERSON") == ["Mary O'Neil-Brown"]


def test_en_surname_comma_given_name_in_capitals_is_one_person() -> None:
    assert texts("Customer: DOE, JANE pays.", cls="PERSON") == ["DOE, JANE"]
    assert texts("represented by DOE, JANE, and", cls="PERSON") == ["DOE, JANE"]


def test_en_double_surname_wrapped_at_its_own_hyphen(
    make_client: Callable[..., TestClient],
) -> None:
    data = detect_api(make_client(), "1. The Insured, Anna Smith-\nJones, signs the policy.")

    covered = [span_text(data, sp) for e in data["entities"] for sp in e["spans"]]
    assert any("Smith" in t and "Jones" in t for t in covered), covered


def test_address_goes_on_after_a_wrap_behind_an_abbreviation() -> None:
    assert texts("Адреса: м.\nЛьвів, вул. Зелена, 8.", cls="ADDRESS") == [
        "м.\nЛьвів, вул. Зелена, 8"
    ]


def test_rnokpp_in_two_groups_of_five_without_a_keyword_is_proposed() -> None:
    assert texts("Також 31826 40979.", cls="TAX_ID") == ["31826 40979"]
    assert texts("Також 12345 67890 грн.", cls="TAX_ID") == []
