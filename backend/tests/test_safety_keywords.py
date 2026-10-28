"""S5b-T2: digit runs after a code keyword are refused unless amount, date or placeholder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.safety_helpers import detector_version, doc, post_doc

Make = Callable[..., TestClient]


def _check(client: TestClient, text: str) -> Any:
    return post_doc(client, doc(detector_version(client), text))


@pytest.mark.parametrize(
    ("text", "leftover"),
    [
        ("ЄДРПОУ: 3412 [A.TAX_ID_1]", "3412"),
        ("Контактний тел. 123 45 67 для зв'язку", "123 45 67"),
        ("Банківський рахунок на підприємстві 4731 8820", "4731 8820"),
        ("Паспорт серії 123456 виданий", "123456"),
        ("Phone: 555-123-4567 office", "555-123-4567"),
        ("ИНН 1234567 указан", "1234567"),
    ],
)
def test_digits_after_code_keyword_are_refused(make_client: Make, text: str, leftover: str) -> None:
    client = make_client()

    response = _check(client, text)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "unmasked_identifier"
    start = text.index(leftover)
    assert any(s[1] <= start and start + len(leftover) <= s[2] for s in body["spans"])
    assert leftover not in response.text


@pytest.mark.parametrize(
    "text",
    [
        "рахунок на суму 12 345,00 грн",
        "№ 5 від 01.02.2026",
        "Рахунок оплачується протягом 10 днів",
        "Знижка 15 % на account 1",
        "тел. [A.PHONE_1]",
        "ЄДРПОУ [A.TAX_ID_1], код [A.TAX_ID_2]",
        "рахунок від 01.02.2026 на 1000 грн",
    ],
)
def test_amounts_dates_short_numbers_and_placeholders_pass(make_client: Make, text: str) -> None:
    client = make_client()

    assert _check(client, text).status_code == 200, text
