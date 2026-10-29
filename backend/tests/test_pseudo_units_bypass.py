"""Round 3 (HIGH): the unit-word negative must not unmask codes.

A code with a keyword (or a Luhn/IBAN code) followed by a unit-like word is
still an identifier: the detector masks it and the safety check refuses an
unmasked copy. Real quantities without a keyword stay unmasked.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import CARD, EDRPOU, IBAN, RNOKPP, break_edrpou, detect
from tests.safety_helpers import detector_version, doc, post_doc
from tests.segment_helpers import block, post_blocks

Make = Callable[..., TestClient]
PHONE = "050 123 45 67"

# (id, text, fragment that must be masked)
CASES = [
    ("rnokpp-sht", f"РНОКПП {RNOKPP} шт.", RNOKPP),
    ("rnokpp-colon-od", f"РНОКПП: {RNOKPP} од.", RNOKPP),
    ("inn-ed", f"ИНН {RNOKPP} ед.", RNOKPP),
    ("taxid-g", f"Tax ID {RNOKPP} g", RNOKPP),
    ("edrpou-tys", f"ЄДРПОУ {EDRPOU} тис", EDRPOU),
    ("iban-sht", f"IBAN {IBAN} шт", IBAN),
    ("iban-glued", f"IBAN {IBAN}шт", IBAN),
    ("card-kg", f"Картка {CARD} kg", CARD),
    ("card-keywordless-kg", f"Оплата {CARD} kg", CARD),
    ("phone-sht", f"тел. {PHONE} шт", PHONE),
]
IDS = [c[0] for c in CASES]
PARAMS = [c[1:] for c in CASES]


@pytest.mark.parametrize(("text", "fragment"), PARAMS, ids=IDS)
def test_units_code_followed_by_unit_word_is_masked(
    make_client: Make, text: str, fragment: str
) -> None:
    data = detect(make_client(), text)

    block_text = data["blocks"][0]["text"]
    at = block_text.index(fragment)
    covered = {
        i for e in data["entities"] for b, s, end in e["spans"] if b == 0 for i in range(s, end)
    }
    assert all(i in covered for i in range(at, at + len(fragment))), data["entities"]


@pytest.mark.parametrize(("text", "fragment"), PARAMS, ids=IDS)
def test_units_unmasked_copy_is_refused_by_the_safety_check(
    make_client: Make, text: str, fragment: str
) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), text))

    assert response.status_code == 422, response.text[:200]
    body = response.json()
    assert body["error"] == "unmasked_identifier"
    at = text.index(fragment)
    assert any(s < at + len(fragment) and at < e for _cid, s, e in body["spans"]), body


@pytest.mark.parametrize(
    "text",
    [
        f"{RNOKPP} шт.",
        f"{break_edrpou(EDRPOU)} шт.",
        f"{RNOKPP[:9]}0 шт.",
        "25 000 мг",
        "1 200 pcs",
        "Замовлено 25 000 мг та 1 200 pcs товару.",
    ],
)
def test_units_quantity_without_keyword_stays_unmasked(make_client: Make, text: str) -> None:
    data = detect(make_client(), text)

    assert data["entities"] == []


def test_units_perf_one_million_number_signs_under_five_seconds(make_client: Make) -> None:
    text = ("№ " * 500_000)[:1_000_000]
    client = make_client()
    start = time.monotonic()

    response = post_blocks(client, [block(text)])

    elapsed = time.monotonic() - start
    assert response.status_code in (200, 422)
    assert elapsed < 5, f"{elapsed:.1f} s"
