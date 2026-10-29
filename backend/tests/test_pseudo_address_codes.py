# ruff: noqa: RUF001
"""Fix: an ADDRESS must stop before a code or contact that follows it on the same line.

The ADDRESS ran to the line end and absorbed IBAN, card, РНОКПП, email, phone,
passport values, so no separate hit existed; the client could unmask the normal
ADDRESS and the value passed the safety check. Values are fictional and
checksum-valid (generated in code).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import CARD, CARD_SPACED, IBAN, IBAN_SPACED, RNOKPP, detect
from tests.safety_helpers import detector_version, doc, hit_spans, post_doc

Make = Callable[..., TestClient]

PREFIX = {
    "uk": "Адреса: м. Одеса, вул. Прикладна, 12, ",
    "ru": "Адрес: г. Одесса, ул. Прикладная, д. 12, ",
    "en": "Address: 12 Applied Street, Odesa, ",
}
PASSPORT = {
    "uk": ("паспорт серії КА № 123456", "123456"),
    "ru": ("паспорт серия КА № 123456", "123456"),
    "en": ("passport No. 123456789", "123456789"),
}


def _values(lang: str) -> list[tuple[str, str, str]]:
    """(id, text of the value, fragment that must be masked outside the ADDRESS)."""
    passport, key = PASSPORT[lang]
    return [
        ("iban", f"IBAN {IBAN}", IBAN),
        ("iban-spaced", f"IBAN {IBAN_SPACED}", IBAN_SPACED),
        ("iban-bare", IBAN, IBAN),
        ("card", f"{CARD}", CARD),
        ("card-spaced", f"{CARD_SPACED}", CARD_SPACED),
        ("rnokpp-no-keyword", RNOKPP, RNOKPP),
        ("email", "ivan.test@example.com", "ivan.test@example.com"),
        ("phone", "+380 44 123 45 67", "+380 44 123 45 67"),
        ("passport", passport, key),
    ]


CASES = [(lang, *v) for lang in sorted(PREFIX) for v in _values(lang)]
IDS = [f"{c[0]}-{c[1]}" for c in CASES]


def _spans_of(data: dict[str, Any], *classes: str) -> list[tuple[int, int, int]]:
    return [
        (b, s, e) for ent in data["entities"] if ent["class"] in classes for b, s, e in ent["spans"]
    ]


@pytest.mark.parametrize(("lang", "_id", "value", "fragment"), CASES, ids=IDS)
def test_address_stops_before_following_code_and_value_is_its_own_entity(
    make_client: Make, lang: str, _id: str, value: str, fragment: str
) -> None:
    text = PREFIX[lang] + value

    data = detect(make_client(), text)

    at = data["blocks"][0]["text"].index(fragment)
    end = at + len(fragment)
    for b, s, e in _spans_of(data, "ADDRESS"):
        assert not (b == 0 and s < end and at < e), f"ADDRESS {s}:{e} overlaps the value"
    other = [
        (b, s, e)
        for ent in data["entities"]
        if ent["class"] != "ADDRESS"
        for b, s, e in ent["spans"]
    ]
    assert any(b == 0 and s <= at and end <= e for b, s, e in other), data["entities"]


@pytest.mark.parametrize(("lang", "_id", "value", "fragment"), CASES, ids=IDS)
def test_address_still_masks_the_street_part_before_the_value(
    make_client: Make, lang: str, _id: str, value: str, fragment: str
) -> None:
    text = PREFIX[lang] + value

    data = detect(make_client(), text)

    street = {"uk": "вул. Прикладна, 12", "ru": "ул. Прикладная, д. 12", "en": "12 Applied Street"}[
        lang
    ]
    assert any(
        street in data["blocks"][b]["text"][s:e] for b, s, e in _spans_of(data, "ADDRESS")
    ), data["entities"]


@pytest.mark.parametrize(("lang", "_id", "value", "fragment"), CASES, ids=IDS)
def test_safety_check_acknowledged_address_does_not_let_the_code_through(
    make_client: Make, lang: str, _id: str, value: str, fragment: str
) -> None:
    client = make_client()
    text = PREFIX[lang] + value
    address = [h for h in hit_spans(client, text) if h[2] == "ADDRESS"]
    assert address, "the detector must still report the ADDRESS hit"
    ack = [["c1", s, e] for s, e, _cls, _prec in address]

    response = post_doc(client, doc(detector_version(client), text, ack=ack))

    assert response.status_code == 422, response.text[:200]
    body = response.json()
    assert body["error"] == "unmasked_identifier"
    at = text.index(fragment)
    assert any(cid == "c1" and s < at + len(fragment) and at < e for cid, s, e in body["spans"]), (
        body
    )
