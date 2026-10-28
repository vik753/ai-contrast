# ruff: noqa: RUF001, E501
"""S5b-T1 AC1: detection rules (ADR 0008 point 1, ADR 0015 point 2).

Small inline examples in UK, RU and EN. A value counts as masked only when one
span covers all of it (a partial mask is a miss). All numbers are fictional.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import (
    CARD,
    CARD_SPACED,
    EDRPOU,
    IBAN,
    IBAN_SPACED,
    RNOKPP,
    all_masked_text,
    break_edrpou,
    covering,
    detect,
    entities_of,
    entity_strings,
)

Make = Callable[..., TestClient]

# (id, text, accepted classes, fragment that one span must contain fully)
MASK_CASES = [
    (
        "email-uk",
        "Надсилайте листи на ivan.test@example.com щодо договору.",
        {"EMAIL"},
        "ivan.test@example.com",
    ),
    (
        "email-at-paren",
        "Пишіть на info(at)example.com у робочі дні.",
        {"EMAIL"},
        "info(at)example.com",
    ),
    (
        "email-at-bracket",
        "Write to sales[at]example.org for questions.",
        {"EMAIL"},
        "sales[at]example.org",
    ),
    ("phone-ua", "Телефон +380 44 123 45 67 працює щодня.", {"PHONE"}, "+380 44 123 45 67"),
    (
        "phone-ua-brackets",
        "Тел. +38 (050) 123-45-67 для зв'язку.",
        {"PHONE"},
        "+38 (050) 123-45-67",
    ),
    ("phone-ua-local", "Тел.: 0501234567 для зв'язку.", {"PHONE"}, "0501234567"),
    ("phone-ru", "Телефон 8 (495) 123-45-67 в рабочие дни.", {"PHONE"}, "8 (495) 123-45-67"),
    ("phone-intl", "Call us at +1 202 555 0143 on weekdays.", {"PHONE"}, "+1 202 555 0143"),
    (
        "url-https",
        "Умови на https://www.example-co.com.ua/terms/page діють.",
        {"URL"},
        "https://www.example-co.com.ua/terms/page",
    ),
    ("url-www", "Details at www.example-shop.com for you.", {"URL"}, "www.example-shop.com"),
    (
        "domain-bare",
        "Сайт компанії example-corp.com.ua містить умови.",
        {"URL"},
        "example-corp.com.ua",
    ),
    ("vin", "VIN: WDB1234561A000001 автомобіля.", {"VEHICLE"}, "WDB1234561A000001"),
    ("plate-ua", "Державний номер АА1234ВВ застрахований.", {"VEHICLE"}, "АА1234ВВ"),
    ("plate-ru", "Государственный номер А123ВС77 застрахован.", {"VEHICLE"}, "А123ВС77"),
    ("passport-uk", "Паспорт серії КА № 123456 виданий раніше.", {"PERSONAL_DOC"}, "123456"),
    ("passport-ru", "Паспорт серия 4510 номер 123456 выдан ранее.", {"PERSONAL_DOC"}, "123456"),
    ("passport-en", "Passport No. 123456789 was issued earlier.", {"PERSONAL_DOC"}, "123456789"),
    ("docno-uk", "Договір № 45/2024-К від 01.02.2024 діє.", {"DOC_NO"}, "45/2024-К"),
    ("docno-ru", "Полис № АВ 1234567 выдан Страхователю.", {"DOC_NO"}, "1234567"),
    ("docno-en", "Contract No. 77-AB/2023 is attached.", {"DOC_NO"}, "77-AB/2023"),
    (
        "cadastral",
        "Кадастровий номер 5110137500:02:001:0123 ділянки.",
        {"ADDRESS"},
        "5110137500:02:001:0123",
    ),
    (
        "address-uk",
        "Адреса: м. Одеса, вул. Тестова, 12, оф. 5, 65000. Страховик сплачує.",
        {"ADDRESS"},
        "вул. Тестова, 12, оф. 5, 65000",
    ),
    (
        "address-ru",
        "Юридический адрес: г. Москва, ул. Тестовая, д. 1\nСтраховщик платит.",
        {"ADDRESS"},
        "ул. Тестовая, д. 1",
    ),
    (
        "address-en",
        "Registered address: 10 Example Street, London, EC1A 1BB. The buyer pays.",
        {"ADDRESS"},
        "10 Example Street, London, EC1A 1BB",
    ),
    ("legal-form-uk", "Страхова компанія ТОВ «Альфа Тест» надає послуги.", {"ORG"}, "Альфа Тест"),
    ("legal-form-ru", "Страховая компания ООО «Бета Тест» оказывает услуги.", {"ORG"}, "Бета Тест"),
    ("legal-form-bank", "Банк АТ «Омега Тест Банк» веде рахунок.", {"ORG"}, "Омега Тест Банк"),
    ("legal-form-en", "Supplier Gamma Test Ltd. delivers the goods.", {"ORG"}, "Gamma Test"),
    (
        "represented-uk",
        "в особі директора Мельниченка Тараса Олеговича, що діє на підставі Статуту",
        {"PERSON"},
        "Мельниченка Тараса Олеговича",
    ),
    (
        "represented-ru",
        "в лице директора Сидорова Ивана Петровича, действующего на основании Устава",
        {"PERSON"},
        "Сидорова Ивана Петровича",
    ),
    (
        "represented-en",
        "represented by its director John Testman, acting under the Charter",
        {"PERSON"},
        "John Testman",
    ),
    ("signature-uk", "____________ /Іваненко І.І./", {"SIGNATURE", "PERSON"}, "Іваненко І.І."),
    (
        "signature-en",
        "Signature: ____________ / J. Testman /",
        {"SIGNATURE", "PERSON"},
        "J. Testman",
    ),
    (
        "fop",
        "ФОП Петренко Іван Іванович надає послуги.",
        {"PERSON", "ORG"},
        "Петренко Іван Іванович",
    ),
    ("tax-labelled-edrpou", f"Код ЄДРПОУ {EDRPOU} вказано у договорі.", {"TAX_ID"}, EDRPOU),
    ("tax-labelled-rnokpp", f"РНОКПП {RNOKPP} вказано у договорі.", {"TAX_ID"}, RNOKPP),
    ("tax-labelled-inn-ru", f"ИНН {RNOKPP} указан в договоре.", {"TAX_ID"}, RNOKPP),
    ("iban-labelled", f"IBAN {IBAN} відкрито у банку.", {"ACCOUNT"}, IBAN),
    ("iban-spaced", f"IBAN {IBAN_SPACED} відкрито у банку.", {"ACCOUNT"}, IBAN_SPACED),
    ("card-labelled", f"Номер картки {CARD} належить клієнту.", {"ACCOUNT"}, CARD),
    (
        "card-spaced-en",
        f"Card number {CARD_SPACED} belongs to the client.",
        {"ACCOUNT"},
        CARD_SPACED,
    ),
    ("birth-date", "Дата народження: 14.03.1985 р. зазначена.", {"PERSONAL_DOC"}, "14.03.1985"),
]


@pytest.mark.parametrize(
    ("text", "classes", "fragment"), [c[1:] for c in MASK_CASES], ids=[c[0] for c in MASK_CASES]
)
def test_detect_identifier_is_covered_by_one_entity_span(
    make_client: Make, text: str, classes: set[str], fragment: str
) -> None:
    data = detect(make_client(), text)

    assert covering(data, fragment, classes), (fragment, data["entities"])


def test_detect_preamble_definition_masks_later_case_forms_in_one_entity(make_client: Make) -> None:
    data = detect(
        make_client(),
        "Страхова компанія ТОВ «Альфа Тест» (далі — Страховик) та Клієнт.",
        "1. Страховик сплачує ТОВ «Альфа Тест» за послуги.",
        "2. Рахунок виставляє «Альфа Тест» до кінця місяця.",
    )

    orgs = [
        e
        for e in entities_of(data, "ORG")
        if any("Альфа Тест" in s for s in entity_strings(data, e))
    ]
    assert len(orgs) == 1
    assert len(orgs[0]["spans"]) >= 3


def test_detect_defined_role_word_is_not_masked(make_client: Make) -> None:
    data = detect(
        make_client(), "ТОВ «Альфа Тест» (далі — Страховик) сплачує, Страховик погоджується."
    )

    assert "Страховик" not in all_masked_text(data)


def test_detect_surname_case_forms_after_preamble_group_into_one_person(make_client: Make) -> None:
    data = detect(
        make_client(),
        "в особі директора Шевченка Андрія Петровича (далі — Директор), що діє на підставі Статуту",
        "1. Договір підписано Шевченком А.П. у присутності свідків.",
        "2. Лист направляється Шевченку А.П. поштою.",
    )

    persons = [
        e
        for e in entities_of(data, "PERSON")
        if any("Шевченк" in s for s in entity_strings(data, e))
    ]
    assert len(persons) == 1
    joined = "\n".join(entity_strings(data, persons[0]))
    assert "Шевченка" in joined
    assert "Шевченком" in joined
    assert "Шевченку" in joined


def test_detect_ru_surname_case_forms_group_into_one_person(make_client: Make) -> None:
    data = detect(
        make_client(),
        "в лице директора Сидорова Ивана Петровича (далее — Директор), действующего на основании Устава",
        "1. Договор подписан Сидоровым И.П. при свидетелях.",
        "2. Письмо направляется Сидорову И.П. почтой.",
    )

    persons = [
        e
        for e in entities_of(data, "PERSON")
        if any("Сидоров" in s for s in entity_strings(data, e))
    ]
    assert len(persons) == 1
    assert len(persons[0]["spans"]) >= 3


def test_detect_initials_in_both_orders_group_with_full_name(make_client: Make) -> None:
    data = detect(
        make_client(),
        "в особі директора Петрова Олега Сергійовича, що діє на підставі Статуту",
        "Підпис: О. С. Петров",
        "Підпис: Петров О.С.",
    )

    persons = [
        e
        for e in entities_of(data, "PERSON")
        if any("Петров" in s for s in entity_strings(data, e))
    ]
    assert len(persons) == 1
    assert len(persons[0]["spans"]) >= 3


def test_detect_common_word_surname_after_preamble_is_masked(make_client: Make) -> None:
    data = detect(
        make_client(),
        "в особі директора Коваль Марії Іванівни, що діє на підставі Статуту",
        "Рахунок підписала Коваль М.І. у присутності свідків.",
    )

    assert covering(data, "Коваль М.І.", {"PERSON", "SIGNATURE"})


def test_detect_quoted_product_name_after_legal_form_context_is_org(make_client: Make) -> None:
    data = detect(
        make_client(), "Страхування за програмою КАСКО «Оптимум Тест» від ТОВ «Альфа Тест»."
    )

    assert covering(data, "Оптимум Тест", {"ORG"})


def test_detect_defined_term_equal_to_masked_name_is_masked(make_client: Make) -> None:
    data = detect(
        make_client(),
        "Страхова компанія ТОВ «Альфа Тест» (далі — «Альфа»), та Клієнт.",
        "1. «Альфа» сплачує вчасно.",
    )

    assert len([s for e in data["entities"] for s in entity_strings(data, e) if "Альфа" in s]) >= 3


# ---------------------------------------------------------------- checksums


def test_detect_edrpou_with_context_is_high_tax_id(make_client: Make) -> None:
    data = detect(make_client(), f"Код ЄДРПОУ {EDRPOU}.")

    [entity] = covering(data, EDRPOU, {"TAX_ID"})
    assert entity["precision"] == "high"


def test_detect_edrpou_in_english_context_is_high(make_client: Make) -> None:
    data = detect(make_client(), f"Company registration code (EDRPOU) {EDRPOU}.")

    [entity] = covering(data, EDRPOU, {"TAX_ID"})
    assert entity["precision"] == "high"


def test_detect_edrpou_context_within_five_tokens_is_high(make_client: Make) -> None:
    data = detect(make_client(), f"ЄДРПОУ підприємства, зареєстрованого в Україні: {EDRPOU}.")

    [entity] = covering(data, EDRPOU, {"TAX_ID"})
    assert entity["precision"] == "high"


def test_detect_edrpou_context_beyond_five_tokens_is_not_high(make_client: Make) -> None:
    far = "один два три чотири п'ять шість сім"
    data = detect(make_client(), f"ЄДРПОУ {far} {EDRPOU}.")

    assert not [e for e in covering(data, EDRPOU, {"TAX_ID"}) if e["precision"] == "high"]


def test_detect_edrpou_checksum_without_context_is_normal_proposal(make_client: Make) -> None:
    data = detect(make_client(), f"Номер {EDRPOU} згадано в тексті.")

    [entity] = covering(data, EDRPOU, {"TAX_ID"})
    assert entity["precision"] == "normal"


def test_detect_rnokpp_with_context_is_high_and_without_is_normal(make_client: Make) -> None:
    labelled = detect(make_client(), f"ІПН {RNOKPP} вказано.")
    bare = detect(make_client(), f"Ідентифікатор {RNOKPP} вказано.")

    assert [e["precision"] for e in covering(labelled, RNOKPP, {"TAX_ID"})] == ["high"]
    assert [e["precision"] for e in covering(bare, RNOKPP, {"TAX_ID"})] == ["normal"]


def test_detect_eight_digits_failing_checksum_without_context_give_no_entity(
    make_client: Make,
) -> None:
    broken = break_edrpou(EDRPOU)

    data = detect(make_client(), f"Номер {broken} згадано в тексті.")

    assert data["entities"] == []


def test_detect_iban_with_and_without_spaces_is_one_entity_per_value(make_client: Make) -> None:
    data = detect(make_client(), f"IBAN {IBAN}.", f"Рахунок {IBAN_SPACED} у банку.")

    accounts = [
        e
        for e in entities_of(data, "ACCOUNT")
        if any(IBAN[:8] in s.replace(" ", "") for s in entity_strings(data, e))
    ]
    assert len(accounts) == 1
    assert len(accounts[0]["spans"]) == 2
    assert accounts[0]["precision"] == "high"


def test_detect_iban_failing_mod97_is_not_high(make_client: Make) -> None:
    bad = IBAN[:-1] + str((int(IBAN[-1]) + 1) % 10)

    data = detect(make_client(), f"IBAN {bad} відкрито.")

    assert not [e for e in covering(data, bad, {"ACCOUNT"}) if e["precision"] == "high"]


def test_detect_card_failing_luhn_is_not_high(make_client: Make) -> None:
    bad = CARD[:-1] + str((int(CARD[-1]) + 1) % 10)

    data = detect(make_client(), f"Номер картки {bad} належить клієнту.")

    assert not [e for e in covering(data, bad, {"ACCOUNT"}) if e["precision"] == "high"]


def test_detect_email_phone_url_are_high_precision(make_client: Make) -> None:
    data = detect(
        make_client(), "Пишіть ivan.test@example.com, тел. +380 44 123 45 67, www.example-shop.com."
    )

    assert {e["class"]: e["precision"] for e in data["entities"]} == {
        "EMAIL": "high",
        "PHONE": "high",
        "URL": "high",
    }


def test_detect_same_email_twice_is_one_entity_with_two_spans(make_client: Make) -> None:
    data = detect(
        make_client(), "Пишіть на ivan.test@example.com.", "Копія на Ivan.Test@Example.com."
    )

    [entity] = entities_of(data, "EMAIL")
    assert len(entity["spans"]) == 2


# ------------------------------------------------------- amounts and controls

NUMBERS = [EDRPOU, RNOKPP, CARD]


def _amounts() -> list[str]:
    e = EDRPOU
    return [
        f"{e[:2]} {e[2:5]} {e[5:]},00 грн",
        f"{e[:2]} {e[2:5]} {e[5:]} UAH",
        f"{e},50 грн",
        f"USD {e[:2]},{e[2:5]},{e[5:]}.00",
        f"{e}.25 EUR",
        f"{RNOKPP[:4]} {RNOKPP[4:7]} {RNOKPP[7:]} гривень",
        f"сума {RNOKPP} руб.",
        "25 %",
        f"{e} %",
        "30 днів",
        f"{e} днів",
        f"{e} kg",
        f"{e} м²",
    ]


@pytest.mark.parametrize("amount", _amounts())
def test_detect_amount_with_checksum_valid_digits_is_never_a_code(
    make_client: Make, amount: str
) -> None:
    data = detect(make_client(), f"1. Страховик сплачує {amount} протягом строку дії.")

    assert data["entities"] == []


def test_detect_amount_even_after_context_word_nearby_is_not_a_code(make_client: Make) -> None:
    e = EDRPOU
    data = detect(make_client(), f"Код: премія становить {e[:2]} {e[2:5]} {e[5:]},00 грн.")

    assert covering(data, e[5:], {"TAX_ID"}) == []


def test_detect_negative_controls_give_no_entity(make_client: Make) -> None:
    data = detect(
        make_client(),
        "1. Страховик, Орендар та Покупець діють у місті Одеса.",
        "2. Buyer pays the Seller within 30 days; the Insurer covers the territory of Kyiv.",
        "3. Покупець сплачує до 15 березня 2025 року суму 10 000 грн, що становить 5 % вартості.",
        "4. Страхове покриття діє на території міста Львів.",
    )

    assert data["entities"] == []


def test_detect_plain_text_has_empty_but_present_reply_fields(make_client: Make) -> None:
    data = detect(make_client(), "1. Страховик сплачує вчасно.")

    assert data["entities"] == []
    assert data["requisites"] == []
    assert data["neutralized"] == []
    assert isinstance(data["detector_version"], str)


def test_detect_all_masked_text_for_party_names_excludes_role_words(make_client: Make) -> None:
    data = detect(
        make_client(),
        "ТОВ «Альфа Тест» (далі — Страховик) і ФОП Петренко Іван Іванович (далі — Клієнт).",
    )

    masked = all_masked_text(data)
    assert "Страховик" not in masked
    assert "Клієнт" not in masked


def test_detect_running_clause_and_heading_text_is_detected(make_client: Make) -> None:
    header = detect(make_client(), "ТОВ «Альфа Тест» — договір", "1. Сплата.", part="header")
    assert covering(header, "Альфа Тест", {"ORG"})

    heading = detect(make_client(), "1. Контакти ivan.test@example.com", "1.1. Текст.")
    assert covering(heading, "ivan.test@example.com", {"EMAIL"})
