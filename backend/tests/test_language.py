# ruff: noqa: RUF001, RUF002 - Cyrillic contract samples are the point of these tests
"""S3-T1 AC5: rule-based language detection on extracted text (no dependency).

Ukrainian-only letters (і, ї, є, ґ) vs Russian-only letters (ы, э, ъ, ё) vs
the Latin share. ``mixed`` when two languages are both significant,
``unknown`` for too little text. Samples are short synthetic contract
snippets; the thresholds themselves are documented by the implementation.
"""

from __future__ import annotations

import pytest

from app.extraction.text import extract_text_file

EN = (
    "SERVICE AGREEMENT. This Agreement is made between the Provider and the Client. "
    "The Client shall pay each invoice within thirty days of receipt. Either party may "
    "terminate this Agreement with sixty days written notice to the other party."
)
UK = (
    "ДОГОВІР ПРО НАДАННЯ ПОСЛУГ. Цей договір укладено між Виконавцем і Замовником. "
    "Замовник сплачує кожен рахунок протягом тридцяти днів з дня його отримання. "
    "Будь-яка сторона може розірвати цей договір, повідомивши іншу сторону письмово "
    "за шістдесят днів. Її обов'язки є чинними до повного виконання."
)
RU = (
    "ДОГОВОР ОБ ОКАЗАНИИ УСЛУГ. Настоящий договор заключён между Исполнителем и Заказчиком. "
    "Заказчик оплачивает каждый счёт в течение тридцати дней с даты его получения. "
    "Любая из сторон вправе расторгнуть этот договор, письменно уведомив другую сторону "
    "за шестьдесят дней. Расходы сторон не возмещаются."
)


def _language(text: str) -> str:
    return extract_text_file(text.encode("utf-8")).language


@pytest.mark.parametrize(
    ("text", "expected"),
    [(EN, "en"), (UK, "uk"), (RU, "ru")],
    ids=["en", "uk", "ru"],
)
def test_language_single_language_contract_detected(text: str, expected: str) -> None:
    assert _language(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(UK, "uk"), (RU, "ru")],
    ids=["uk", "ru"],
)
def test_language_cp1251_contract_detected(text: str, expected: str) -> None:
    assert extract_text_file(text.encode("cp1251")).language == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"{EN}\n\n{UK}", id="en-uk-bilingual"),
        pytest.param(f"{EN}\n\n{RU}", id="en-ru-bilingual"),
        pytest.param(f"{UK}\n\n{RU}", id="uk-ru"),
    ],
)
def test_language_two_significant_languages_is_mixed(text: str) -> None:
    assert _language(text) == "mixed"


def test_language_english_with_one_ukrainian_name_stays_english() -> None:
    assert _language(f"{EN} Signed for the Client: Іван Петренко.") == "en"


def test_language_ukrainian_with_latin_product_name_stays_ukrainian() -> None:
    assert _language(f"{UK} Документ підготовлено у Microsoft Word.") == "uk"


def test_language_russian_with_latin_product_name_stays_russian() -> None:
    assert _language(f"{RU} Документ подготовлен в Microsoft Word.") == "ru"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("OK", id="two-letters"),
        pytest.param("12.03.2026 № 15/7 — 1 000,00", id="numbers-only"),
        pytest.param("Іі", id="two-ukrainian-letters"),
    ],
)
def test_language_too_little_text_is_unknown(text: str) -> None:
    assert _language(text) == "unknown"
