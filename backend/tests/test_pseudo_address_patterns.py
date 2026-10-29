# ruff: noqa: RUF001
"""An ADDRESS stops before a phone, plate, VIN or checksum code that follows it.

Values are fictional; the 10-digit code is checksum-valid (generated in code).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import detect, rnokpp

Make = Callable[..., TestClient]

PREFIX = "Адреса: м. Одеса, вул. Прикладна, 12, "
CODE = rnokpp("312345678")
CASES = [
    ("phone", "050 123 45 67", "PHONE", "high"),
    ("phone-dashes", "050-123-45-67", "PHONE", "high"),
    ("plate-ua", "ВН 1234 АХ", "VEHICLE", None),
    ("plate-compact", "ВН1234АХ", "VEHICLE", None),
    ("vin", "WVWZZZ1JZXW000001", "VEHICLE", None),
    ("rnokpp-after-flat", "кв. " + CODE, "TAX_ID", None),
    ("rnokpp-bare", CODE, "TAX_ID", None),
]


@pytest.mark.parametrize(("_id", "value", "cls", "precision"), CASES, ids=[c[0] for c in CASES])
def test_address_stops_before_pattern_and_value_is_its_own_entity(
    make_client: Make, _id: str, value: str, cls: str, precision: str | None
) -> None:
    data = detect(make_client(), PREFIX + value)

    fragment = CODE if "rnokpp" in _id else value
    at = data["blocks"][0]["text"].index(fragment)
    end = at + len(fragment)
    for ent in data["entities"]:
        if ent["class"] == "ADDRESS":
            for b, s, e in ent["spans"]:
                assert not (b == 0 and s < end and at < e), f"ADDRESS {s}:{e} overlaps the value"
    owners = [
        ent
        for ent in data["entities"]
        if ent["class"] == cls and any(b == 0 and s <= at and end <= e for b, s, e in ent["spans"])
    ]
    assert owners, data["entities"]
    if precision is not None:
        assert owners[0]["precision"] == precision


@pytest.mark.parametrize(("_id", "value", "cls", "precision"), CASES, ids=[c[0] for c in CASES])
def test_address_still_masks_the_street_before_the_pattern(
    make_client: Make, _id: str, value: str, cls: str, precision: str | None
) -> None:
    data = detect(make_client(), PREFIX + value)

    assert any(
        "вул. Прикладна, 12" in data["blocks"][b]["text"][s:e]
        for ent in data["entities"]
        if ent["class"] == "ADDRESS"
        for b, s, e in ent["spans"]
    ), data["entities"]
