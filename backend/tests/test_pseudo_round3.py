# ruff: noqa: RUF001
"""Detector round 3: national and toll-free phones, URLs with paths, spelled-out legal forms,
foreign VAT, grouped ИНН, sort codes, driver licence and passport variants, spaced plates,
English persons and addresses, quantities with units, more requisites headings.

Direct calls to ``detect``; every value is synthetic. Each rule has near-miss negatives.
"""

from __future__ import annotations

import pytest

from app.pseudo.detector import detect
from app.segment import patterns
from app.segment.model import Clause

HEADING = "Реквізити та підписи сторін"


def texts(*blocks: str, cls: str | None = None) -> list[str]:
    result = detect(list(blocks), [])
    spans = [(b, s, e, entity.cls) for entity in result.entities for b, s, e in entity.spans]
    return [blocks[b][s:e] for b, s, e, c in sorted(spans) if cls is None or c == cls]


# ------------------------------------------------------------------------ phones


@pytest.mark.parametrize(
    ("text", "phone"),
    [
        ("Гаряча лінія: 0 800 507 321.", "0 800 507 321"),
        ("Дзвоніть 0800 507 321 щодня.", "0800 507 321"),
        ("Позвоните 8-800-100-24-77 сегодня.", "8-800-100-24-77"),
        ("Freephone 0800 123 4567 is open.", "0800 123 4567"),
        ("Call 88001002477 now.", "88001002477"),
    ],
)
def test_toll_free_phone_needs_no_keyword(text: str, phone: str) -> None:
    assert texts(text, cls="PHONE") == [phone]


@pytest.mark.parametrize(
    "text",
    [
        "Сума 0 800 507 321 грн.",
        "Партія 0 800 507 321 штук.",
        "Позиція 8 800 100 шт.",
        "Number 1.0 800 507 321 here.",
        "Ціна 0 800 5 грн.",
    ],
)
def test_toll_free_near_misses_are_not_phones(text: str) -> None:
    assert texts(text, cls="PHONE") == []


@pytest.mark.parametrize(
    ("text", "phone"),
    [
        ("Please phone 0117 496 0842 today.", "0117 496 0842"),
        ("For urgent claims, phone 020 7946 0321 any day.", "020 7946 0321"),
        ("Call: 01632 960 001 now.", "01632 960 001"),
        ("Телефонуйте 0117 496 0842 щодня.", "0117 496 0842"),
    ],
)
def test_national_phone_after_a_phone_word(text: str, phone: str) -> None:
    assert texts(text, cls="PHONE") == [phone]


@pytest.mark.parametrize(
    "text",
    [
        "Code 0117 496 0842 is in the list.",
        "Please phone 0117 496 for details.",
        "Phone 0117 496 0842 EUR is wrong.",
        "Phone 1117 496 0842 today.",
    ],
)
def test_national_phone_near_misses(text: str) -> None:
    assert texts(text, cls="PHONE") == []


# --------------------------------------------------------------------------- URL


def test_bare_domain_with_path_is_one_url() -> None:
    assert texts("Forms are at northgate-claims.com/forms.", cls="URL") == [
        "northgate-claims.com/forms"
    ]
    assert texts("Open ironwood-cover.co.uk/help/a-b or write.", cls="URL") == [
        "ironwood-cover.co.uk/help/a-b"
    ]


def test_bare_domain_without_path_and_clause_references_stay_as_before() -> None:
    assert texts("Visit example.com today.", cls="URL") == ["example.com"]
    assert texts("See clause 4.2/b and annex 3/1.", cls="URL") == []
    assert texts("File notes.txt/ and 1.5/2 apply.", cls="URL") == []


# ---------------------------------------------------------------------------- ORG


def test_spelled_out_legal_form_is_part_of_the_organisation() -> None:
    assert texts("Заказчик — Общество с ограниченной ответственностью «Вектор Плюс», далее.") == [
        "Общество с ограниченной ответственностью «Вектор Плюс»"
    ]
    assert texts("Акционерное общество «Горизонт-Сервис» в лице директора.", cls="ORG") == [
        "Акционерное общество «Горизонт-Сервис»"
    ]
    assert texts("Товариство з обмеженою відповідальністю «Омега Трейд» уклало.", cls="ORG") == [
        "Товариство з обмеженою відповідальністю «Омега Трейд»"
    ]
    assert texts('Limited liability company "Apex Group" signs.', cls="ORG") == [
        'Limited liability company "Apex Group"'
    ]


def test_case_form_of_the_legal_form_is_found() -> None:
    result = texts("в лице Общества с ограниченной ответственностью «Орбита Групп».", cls="ORG")
    assert result == ["Общества с ограниченной ответственностью «Орбита Групп»"]


@pytest.mark.parametrize(
    "text",
    [
        "Общество вправе расторгнуть договор.",
        "Акционерное общество несёт ответственность.",
        "Общество с ограниченной свободой действий.",
        "Товариство з обмеженою кількістю місць.",
    ],
)
def test_legal_form_words_without_a_name_are_not_organisations(text: str) -> None:
    assert texts(text, cls="ORG") == []


# --------------------------------------------------------------------------- tax


def test_foreign_vat_with_country_prefix_and_spaces() -> None:
    assert texts("Постачальник сплачує ПДВ, VAT DE 812 3456 78, у країні.", cls="TAX_ID") == [
        "DE 812 3456 78"
    ]
    assert texts("Номер VAT PL 526 1234 56.", cls="TAX_ID") == ["PL 526 1234 56"]
    assert texts("VAT: GB 123 4567 89", cls="TAX_ID") == ["GB 123 4567 89"]


@pytest.mark.parametrize(
    "text",
    [
        "Ціна включає VAT 20 %.",
        "VAT No 12345678 applies.",
        "VAT in 2025 12 31 days.",
        "DE 812 3456 78",
    ],
)
def test_foreign_vat_near_misses(text: str) -> None:
    assert not [t for t in texts(text, cls="TAX_ID") if t.startswith(("DE", "No", "in"))]


def test_inn12_in_groups_needs_a_valid_check_digit() -> None:
    assert texts("7801 2345 6724", cls="TAX_ID") == ["7801 2345 6724"]
    assert texts("5029 8765 4365", cls="TAX_ID") == ["5029 8765 4365"]
    assert texts("7801 2345 6725", cls="TAX_ID") == []


def test_inn12_in_groups_is_not_a_card_or_an_amount() -> None:
    assert texts("7801 2345 6724 руб.", cls="TAX_ID") == []
    assert texts("7801 2345 6724 8765", cls="TAX_ID") == []


# ------------------------------------------------------------------------ account


def test_account_after_spelled_out_labels_with_yo() -> None:
    assert texts("Расчётный счёт 40702810900000045678 в банке.", cls="ACCOUNT") == [
        "40702810900000045678"
    ]
    assert texts("Через корреспондентский счёт 30101810400000000123 платежи.", cls="ACCOUNT") == [
        "30101810400000000123"
    ]


def test_twenty_digits_without_a_label_are_not_an_account() -> None:
    assert texts("Номер заказа 40702810900000045678 принят.", cls="ACCOUNT") == []


def test_sort_code_and_account_number() -> None:
    result = texts("Sort code 20-45-67, account 41234567.", cls="ACCOUNT")
    assert result == ["20-45-67", "41234567"]
    result = texts("Pay to sort code 30-91-22 and account number 90817263.", cls="ACCOUNT")
    assert result == ["30-91-22", "90817263"]


def test_sort_code_near_misses() -> None:
    assert texts("Payment is due within 14-30 days.", cls="ACCOUNT") == []
    assert texts("Dates 20-45-67 are fixed.", cls="ACCOUNT") == []
    assert texts("Account 41234567 is open.", cls="ACCOUNT") == []


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("Оплата по счёт-фактура № 4521 в срок.", "4521"),
        ("Рахунок-фактура № 77812 сплачено.", "77812"),
        ("Накладная No. 90431 получена.", "90431"),
        ("Invoice # 5521 is due.", "5521"),
        ("Policy #8812345 applies.", "8812345"),
        ("Довіреність № 31 від 5 травня.", "31"),
    ],
)
def test_number_after_a_document_word_is_doc_no(text: str, number: str) -> None:
    assert texts(text, cls="DOC_NO") == [number]


@pytest.mark.parametrize(
    "text",
    ["Партия № 4521 штук.", "Item # 4521 units.", "Hash # 4521 here.", "Оплата № 4521 в срок."],
)
def test_number_without_a_document_word_or_with_a_unit_is_not_doc_no(text: str) -> None:
    assert texts(text, cls="DOC_NO") == []


# -------------------------------------------------------------------- documents


def test_driver_licence_in_case_forms() -> None:
    assert texts("діє за посвідченням водія ЛАВ 220915.", cls="PERSONAL_DOC") == ["ЛАВ 220915"]
    assert texts("посвідчення водія ХМК 305172 при підписанні.", cls="PERSONAL_DOC") == [
        "ХМК 305172"
    ]
    assert texts("водительского удостоверения АВ 123456 выдано.", cls="PERSONAL_DOC") == [
        "АВ 123456"
    ]
    assert texts("Driver's licence MORGA 657054 issued.", cls="PERSONAL_DOC") == []


def test_driver_licence_word_without_a_number_is_nothing() -> None:
    assert texts("Посвідчення водія видане в Одесі.", cls="PERSONAL_DOC") == []


def test_passport_with_series_pairs_and_numero_sign() -> None:
    assert texts("Паспорт гражданина РФ серия 45 12 № 678901 выдан.", cls="PERSONAL_DOC") == [
        "45 12 № 678901"
    ]
    assert texts("паспорт, серия 03 19 № 241150.", cls="PERSONAL_DOC") == ["03 19 № 241150"]
    assert texts("серия 4512 № 678901", cls="PERSONAL_DOC") == ["4512 № 678901"]


def test_series_near_misses() -> None:
    assert texts("серия 45 12 № 6789", cls="PERSONAL_DOC") == []
    assert texts("серия 45 книг № 678901", cls="PERSONAL_DOC") == []
    assert texts("серия 45 12", cls="PERSONAL_DOC") == []


def test_ru_plate_with_spaces_between_groups() -> None:
    assert texts("с госномером К 482 МР 77 передан", cls="VEHICLE") == ["К 482 МР 77"]
    assert texts("(номер А 905 ОН 199) возвращено", cls="VEHICLE") == ["А 905 ОН 199"]


@pytest.mark.parametrize(
    "text",
    ["Кабина 3 рассчитана на 482 кг.", "к 482 мр 77 малые буквы", "К 48 МР 77", "К 482 МР 7"],
)
def test_spaced_plate_near_misses(text: str) -> None:
    assert texts(text, cls="VEHICLE") == []


# ----------------------------------------------------------------------- persons


def test_person_before_a_job_title() -> None:
    assert texts("Daniel Marlow, Chief Executive Officer", cls="PERSON") == ["Daniel Marlow"]
    assert texts("J. Thornberry, Finance Director", cls="PERSON") == ["J. Thornberry"]
    assert texts("Priya Okonkwo-Hale, Head of Legal", cls="PERSON") == ["Priya Okonkwo-Hale"]
    assert texts("M. Delacroix, Operations Manager", cls="PERSON") == ["M. Delacroix"]


@pytest.mark.parametrize(
    "text",
    [
        "Finance Director approves all invoices.",
        "Delivery, Head of Legal",
        "Northwind Logistics Ltd, Chief Executive Officer",
        "Daniel Marlow, the Chief Executive Officer",
        "Daniel Marlow, Plumber",
    ],
)
def test_job_title_near_misses(text: str) -> None:
    assert texts(text, cls="PERSON") == []


def test_person_after_notice_lead_ins() -> None:
    assert texts("Notices to: Helena Brandt, at the address.", cls="PERSON") == ["Helena Brandt"]
    assert texts("Questions go to Ruth Baker in Compliance.", cls="PERSON") == ["Ruth Baker"]
    assert texts("Please address questions to Owen Cook.", cls="PERSON") == ["Owen Cook"]
    assert texts("Attention: Mary Stone", cls="PERSON") == ["Mary Stone"]


def test_lead_in_without_a_name_is_nothing() -> None:
    assert texts("Questions go to the claims team.", cls="PERSON") == []
    assert texts("Notices to: the Buyer.", cls="PERSON") == []


def test_whole_name_after_authorised_signatory() -> None:
    assert texts("Authorised signatory: Marcus Delgado, Managing Director", cls="PERSON") == [
        "Marcus Delgado"
    ]
    assert texts("Authorised signatory: Ingrid Holm (Director)", cls="PERSON") == ["Ingrid Holm"]
    assert texts("Head of Finance: Alice Prentiss", cls="PERSON") == ["Alice Prentiss"]
    assert texts("Генеральний директор: Олег Бондаренко", cls="PERSON") == ["Олег Бондаренко"]


def test_job_title_with_a_lone_word_is_not_a_name() -> None:
    assert texts("Director: Finance", cls="PERSON") == []


def test_name_as_sentence_subject_before_an_action_verb() -> None:
    assert texts("Tobias Wren signs on behalf of the Supplier.", cls="PERSON") == ["Tobias Wren"]
    assert texts("Hello. Lena Voss confirms receipt.", cls="PERSON") == ["Lena Voss"]


@pytest.mark.parametrize(
    "text",
    [
        "Receipt is confirmed by the Buyer.",
        "Delivery follows payment.",
        "Purchase Order approved by the Buyer.",
        "Service Provider signs here.",
        "Tobias Wren is here.",
        "We think Tobias Wren signs.",
    ],
)
def test_sentence_subject_near_misses(text: str) -> None:
    assert texts(text, cls="PERSON") == []


def test_latin_name_with_cyrillic_form_in_brackets_is_one_person() -> None:
    result = detect(["Signed by Iryna Kovalenko (Ірина Коваленко) for the Supplier."], [])
    assert len(result.entities) == 1
    assert len(result.entities[0].spans) == 2
    result = detect(["Director Petro Hnatyuk (Петро Гнатюк) approved."], [])
    assert [e.cls for e in result.entities] == ["PERSON"]
    assert len(result.entities[0].spans) == 2


def test_bracket_form_must_be_the_same_name() -> None:
    assert texts("Signed by Iryna Kovalenko (Олег Шевченко) for the Supplier.", cls="PERSON") == []
    assert texts("Northwind Logistics (Нортвінд Логістікс) signs.", cls="PERSON") == []


# --------------------------------------------------------------------- addresses


def test_english_address_with_trailing_country_and_unit_prefix() -> None:
    assert texts("Office: 14 Linden Road, Bristol BS1 4XY, United Kingdom.", cls="ADDRESS") == [
        "14 Linden Road, Bristol BS1 4XY, United Kingdom"
    ]
    assert texts("Delivery: Warehouse 5, 220 Quay Street, Leeds LS2 7EQ.", cls="ADDRESS") == [
        "Warehouse 5, 220 Quay Street, Leeds LS2 7EQ"
    ]
    assert texts("Premises: Unit 7, 18 Mill Lane, Cardiff CF10 3AT.", cls="ADDRESS") == [
        "Unit 7, 18 Mill Lane, Cardiff CF10 3AT"
    ]


def test_transliterated_address_without_a_keyword() -> None:
    assert texts("He lives at 27 Shevchenko Street, apt. 12, Kharkiv 61001, Ukraine.") == [
        "27 Shevchenko Street, apt. 12, Kharkiv 61001, Ukraine"
    ]


def test_country_is_not_added_without_an_address() -> None:
    assert texts("Disputes go to courts in United Kingdom.", cls="ADDRESS") == []
    assert texts("14 Linden Road, Bristol BS1 4XY, Unitedx", cls="ADDRESS") == [
        "14 Linden Road, Bristol BS1 4XY"
    ]
    assert texts("Pay 5, 220 days later.", cls="ADDRESS") == []


# --------------------------------------------------------------------- quantities


@pytest.mark.parametrize(
    "text",
    [
        "Партия 7712345671 штук.",
        "Масса 3012345670 мг.",
        "Поставка 3521741827 экз.",
        "Партія 7712345671 од.",
        "Weight 3012345670 g.",
        "Total 3521741827 mg.",
        "Count 7712345671 units.",
        "Batch 7712345671 pieces.",
        "Batch 7712345671 pcs.",
    ],
)
def test_a_number_before_a_unit_word_is_never_masked(text: str) -> None:
    assert texts(text) == []


def test_the_same_number_with_a_tax_keyword_is_still_found() -> None:
    assert texts("РНОКПП 3012345670 виданий.", cls="TAX_ID") == ["3012345670"]


# ---------------------------------------------------------------------- requisites


def _lines(*lines: str) -> dict[str, str]:
    blocks = ["1. Terms.", HEADING, *lines]
    clause = Clause(
        id="c1",
        number="1",
        level=1,
        part_index=0,
        section_kind=None,
        part="body",
        pages=[],
        spans=[(0, 0, len(blocks[0]))],
        heading_span=None,
    )
    sections = Clause(
        id="c2",
        number=None,
        level=1,
        part_index=0,
        section_kind="requisites",
        part="body",
        pages=[],
        spans=[(i, 0, len(b)) for i, b in enumerate(blocks) if i >= 1],
        heading_span=(1, 0, len(HEADING)),
    )
    result = detect(blocks, [clause, sections])
    actions: dict[str, str] = {}
    for _, decided in result.requisites:
        for (b, s, e), action in decided:
            actions[blocks[b][s:e].strip()] = action
    return actions


def test_label_value_lines_with_e_mail_bank_and_two_pairs_are_dropped() -> None:
    actions = _lines(
        "E-mail: office@garant-centr.com.ua",
        "Банк: «Південний кредит»",
        "Тел.: +380 44 555 01 23, e-mail: claims@garant-centr.com.ua",
        "Sort code: 40-55-12 Account: 70234981",
    )
    assert set(actions.values()) == {"drop"}


def test_second_role_title_and_full_name_is_dropped_but_a_condition_is_kept() -> None:
    actions = _lines(
        "Генеральний директор: Олег Бондаренко",
        "Головний бухгалтер: Ірина Савчук",
        "Chief Financial Officer: Nora Whitfield",
        "Head of Finance: Alice Prentiss",
        "Головний бухгалтер зобов'язаний сплатити штраф",
        "Tobias Wren signs on behalf of the Licensor",
    )
    assert list(actions.values()) == ["drop"] * 4 + ["keep"] * 2


@pytest.mark.parametrize(
    "heading",
    [
        "Corporate particulars and execution",
        "Final particulars of the parties",
        "Адреси, реквізити та підписи",
        "Банковские реквизиты и подписи",
    ],
)
def test_more_requisites_headings_open_the_section(heading: str) -> None:
    assert patterns.is_requisites_title(heading)
    assert not patterns.is_requisites_title(heading + " and more words")
