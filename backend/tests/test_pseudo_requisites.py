# ruff: noqa: RUF001
"""S5b-T1 AC4: requisites section, line by line (ADR 0008 point 2, ADR 0015 point 1)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.pseudo_helpers import (
    EDRPOU,
    IBAN,
    REQUISITES_HEADING,
    detect_blocks,
    requisite_actions,
    requisites_doc,
)
from tests.segment_helpers import block

Make = Callable[..., TestClient]


def test_requisites_precondition_heading_makes_requisites_clause(make_client: Make) -> None:
    data = detect_blocks(make_client(), requisites_doc("ЄДРПОУ: " + EDRPOU))

    assert any(c["section_kind"] == "requisites" for c in data["clauses"])
    assert [r["clause"] for r in data["requisites"]] == [
        c["id"] for c in data["clauses"] if c["section_kind"] == "requisites"
    ]


def test_requisites_identifier_label_and_role_lines_are_dropped(make_client: Make) -> None:
    lines = [
        "Страховик",
        f"ЄДРПОУ: {EDRPOU}",
        f"IBAN: {IBAN}",
        "Тел.: +380 44 123 45 67",
        "Email: info@example.com",
        "Адреса: м. Одеса, вул. Тестова, 12",
    ]

    data = detect_blocks(make_client(), requisites_doc(*lines))

    actions = requisite_actions(data)
    assert {actions[line] for line in lines} == {"drop"}
    assert not any(w["code"] == "requisites_condition" for w in data["warnings"])


def test_requisites_signature_line_is_dropped(make_client: Make) -> None:
    line = "____________ /Іваненко І.І./"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "drop"


def test_requisites_obligation_line_with_surname_is_kept(make_client: Make) -> None:
    line = "Іваненко І.І. відмовляється від претензій"

    data = detect_blocks(make_client(), requisites_doc("Страховик", line))

    assert requisite_actions(data)[line] == "keep"


def test_requisites_penalty_line_with_percent_is_kept(make_client: Make) -> None:
    line = "Неустойка 50 %"

    data = detect_blocks(make_client(), requisites_doc("Страховик", line))

    assert requisite_actions(data)[line] == "keep"


def test_requisites_kept_line_adds_requisites_condition_warning_to_clause(
    make_client: Make,
) -> None:
    data = detect_blocks(make_client(), requisites_doc("Неустойка 50 %"))

    clause = next(c["id"] for c in data["clauses"] if c["section_kind"] == "requisites")
    assert {"code": "requisites_condition", "clause": clause} in [
        {"code": w["code"], "clause": w["clause"]} for w in data["warnings"]
    ]


def test_requisites_ru_and_en_obligation_markers_keep_the_line(make_client: Make) -> None:
    lines = [
        "Страхователь обязуется оплатить штраф",
        "Покупатель соглашается с условиями",
        "The Buyer agrees to pay on demand",
        "Seller shall deliver within 5 days",
    ]

    data = detect_blocks(make_client(), requisites_doc(*lines))

    actions = requisite_actions(data)
    assert {actions[line] for line in lines} == {"keep"}


def test_requisites_line_with_date_or_unit_is_kept(make_client: Make) -> None:
    lines = ["Дійсний до 31.12.2030", "Строк 30 днів"]

    data = detect_blocks(make_client(), requisites_doc(*lines))

    assert {requisite_actions(data)[line] for line in lines} == {"keep"}


def test_requisites_line_with_unclassified_word_is_kept(make_client: Make) -> None:
    line = "Особливі умови домовленості сторін"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "keep"


def test_requisites_identifier_with_amount_in_same_line_is_kept(make_client: Make) -> None:
    line = f"ЄДРПОУ: {EDRPOU} 5 000 грн"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "keep"


def test_requisites_lines_in_one_block_are_decided_separately(make_client: Make) -> None:
    blocks = [
        block("1. The parties agree."),
        block(REQUISITES_HEADING),
        block(f"ЄДРПОУ: {EDRPOU}\nНеустойка 50 %"),
    ]

    data = detect_blocks(make_client(), blocks)

    actions = requisite_actions(data)
    assert actions[f"ЄДРПОУ: {EDRPOU}"] == "drop"
    assert actions["Неустойка 50 %"] == "keep"


def test_requisites_lines_outside_the_section_are_never_listed(make_client: Make) -> None:
    blocks = [block("1. ЄДРПОУ: " + EDRPOU), block("2. Інший пункт.")]

    data = detect_blocks(make_client(), blocks)

    assert data["requisites"] == []


def test_requisites_every_listed_line_span_is_inside_the_clause(make_client: Make) -> None:
    data = detect_blocks(make_client(), requisites_doc(f"ЄДРПОУ: {EDRPOU}", "Неустойка 50 %"))

    clauses = {c["id"]: c for c in data["clauses"]}
    for item in data["requisites"]:
        for line in item["lines"]:
            b, s, e = line["span"]
            assert any(
                sb == b and ss <= s and e <= se for sb, ss, se in clauses[item["clause"]]["spans"]
            )
            assert line["action"] in ("drop", "keep")
