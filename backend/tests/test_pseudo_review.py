# ruff: noqa: RUF001, E501
"""S5b-T1 review round 1 (PR #58): leaks found by the security review.

Rule for every value: no character of it stays outside an entity span, or the
requisites line is kept.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import (
    IBAN,
    covering,
    detect,
    detect_blocks,
    edrpou,
    entities_of,
    requisite_actions,
    requisites_doc,
    rnokpp,
    span_text,
)
from tests.segment_helpers import block, post_blocks

Make = Callable[..., TestClient]


def _covered(data: dict[str, Any]) -> set[tuple[int, int]]:
    return {(b, i) for e in data["entities"] for b, s, end in e["spans"] for i in range(s, end)}


def uncovered(
    data: dict[str, Any], value: str, *, only_block: int | None = None
) -> list[tuple[int, int]]:
    """Positions of ``value`` occurrences (as (block, start)) that have an uncovered character."""
    cov = _covered(data)
    bad: list[tuple[int, int]] = []
    for b, blk in enumerate(data["blocks"]):
        if only_block is not None and b != only_block:
            continue
        text = blk["text"]
        at = text.find(value)
        while at != -1:
            if any((b, i) not in cov for i in range(at, at + len(value))):
                bad.append((b, at))
            at = text.find(value, at + 1)
    return bad


def assert_masked(data: dict[str, Any], value: str, *, only_block: int | None = None) -> None:
    assert any(value in blk["text"] for blk in data["blocks"]), f"{value!r} not in blocks"
    assert uncovered(data, value, only_block=only_block) == [], value


# -------------------------------------------------------------- 1 requisites


def test_review_requisites_address_line_with_obligation_and_amount_is_kept(
    make_client: Make,
) -> None:
    line = "Адреса: вул. Прикладна 12 Замовник сплачує штраф 1000000 грн у разі розірвання договору"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "keep"


def test_review_requisites_address_ends_before_the_next_sentence_words(make_client: Make) -> None:
    line = "Адреса: вул. Прикладна 12 Замовник сплачує штраф 1000000 грн у разі розірвання договору"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert_masked(data, "вул. Прикладна 12")
    for e in entities_of(data, "ADDRESS"):
        for sp in e["spans"]:
            assert "Замовник" not in span_text(data, sp)


def test_review_requisites_signature_line_with_extra_words_is_kept(make_client: Make) -> None:
    line = "____________ /Іваненко І.І. Не Несе Відповідальності/"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "keep"


def test_review_requisites_masked_part_with_amount_inside_still_keeps_line(
    make_client: Make,
) -> None:
    line = "Адреса: вул. Прикладна 12, 25 %"

    data = detect_blocks(make_client(), requisites_doc(line))

    assert requisite_actions(data)[line] == "keep"


# ------------------------------------------------------------ 2 combining marks


def test_review_combining_accent_surname_masked_in_definition_and_later_plain_form(
    make_client: Make,
) -> None:
    data = detect(
        make_client(),
        "в особі директора Шевче́нко Тарас Григорович, що діє на підставі Статуту",
        "1. Директор Шевченко підписав договір.",
    )

    assert_masked(data, "Шевче́нко")
    assert_masked(data, "Шевченко", only_block=1)


# ------------------------------------------------------------ 3 ORG later mentions


def test_review_org_later_bare_mentions_are_masked_and_grouped(make_client: Make) -> None:
    data = detect(
        make_client(),
        "Сторони: ТОВ «Альфа-Гарант» та ТОВ «Бета» уклали цей договір.",
        "1. Платіж Альфа-Гарант, АЛЬФА-ГАРАНТ та Бета сплачено вчасно.",
    )

    for value in ("Альфа-Гарант", "АЛЬФА-ГАРАНТ", "Бета"):
        assert_masked(data, value, only_block=1)
    [alpha] = [
        e for e in covering(data, "Альфа-Гарант", {"ORG"}) if any(sp[0] == 0 for sp in e["spans"])
    ]
    in_body = [sp for sp in alpha["spans"] if sp[0] == 1]
    assert len(in_body) == 2


# --------------------------------------------------- 4 codes and contacts


def _spaced(value: str, sizes: list[int], sep: str = " ") -> str:
    parts, at = [], 0
    for n in sizes:
        parts.append(value[at : at + n])
        at += n
    return sep.join(parts)


def test_review_edrpou_with_spaced_digits_after_keyword_is_fully_masked(make_client: Make) -> None:
    value = _spaced(edrpou("3412345"), [2, 2, 2, 2])

    data = detect(make_client(), f"Код ЄДРПОУ {value} вказано.")

    assert_masked(data, value)


def test_review_rnokpp_with_hyphen_after_keyword_is_fully_masked(make_client: Make) -> None:
    value = _spaced(rnokpp("312345678"), [5, 5], "-")

    data = detect(make_client(), f"РНОКПП {value} вказано.")

    assert_masked(data, value)


def test_review_iban_with_hyphen_inside_is_fully_masked(make_client: Make) -> None:
    value = IBAN[:12] + "-" + IBAN[12:]

    data = detect(make_client(), f"IBAN {value} відкрито.")

    assert_masked(data, value)


def test_review_iban_split_across_two_lines_in_one_clause_is_fully_masked(
    make_client: Make,
) -> None:
    head, tail = IBAN[:15], IBAN[15:]

    data = detect(make_client(), f"1. Рахунок IBAN {head}\n{tail} відкрито у банку.")

    assert_masked(data, head)
    assert_masked(data, tail)


@pytest.mark.parametrize("phone", ["050 123 45 67", "0501234567"])
def test_review_domestic_phone_after_keyword_is_fully_masked(make_client: Make, phone: str) -> None:
    data = detect(make_client(), f"Тел. {phone} працює щодня.")

    assert_masked(data, phone)
    assert covering(data, phone, {"PHONE"})


# ------------------------------------------------------------- 5 emails, names


@pytest.mark.parametrize(
    "email",
    [
        "ivan [at] example [dot] com",
        "ivan at example dot com",
        "іван@приклад.укр",
        "ivan(собака)example.com",
    ],
)
def test_review_obfuscated_or_unicode_email_is_fully_masked(make_client: Make, email: str) -> None:
    data = detect(make_client(), f"Пишіть на {email} щодо договору.")

    assert_masked(data, email)
    assert covering(data, email, {"EMAIL"})


def test_review_surname_comma_given_name_both_parts_masked(make_client: Make) -> None:
    data = detect(
        make_client(), "The seller is represented by DOE, JANE, acting under the Charter."
    )

    assert_masked(data, "DOE, JANE")


def test_review_defined_surname_with_possessive_is_masked_later(make_client: Make) -> None:
    data = detect(
        make_client(),
        "The buyer is represented by its director Robert Smith (hereinafter Smith), acting under the Charter.",
        "1. Smith's signature is required.",
    )

    assert_masked(data, "Smith", only_block=1)


# ---------------------------------------------------------------- 6 performance


@pytest.mark.parametrize(("name", "unit"), [("number-sign", "№ "), ("www-comma", "www.a,")])
def test_review_one_million_characters_of_repeats_detect_under_six_seconds(
    make_client: Make, name: str, unit: str
) -> None:
    text = (unit * (1_000_000 // len(unit) + 1))[:1_000_000]
    client = make_client()
    start = time.monotonic()

    response = post_blocks(client, [block(text)])

    elapsed = time.monotonic() - start
    assert response.status_code in (200, 422), response.text[:100]
    assert elapsed < 6, f"{name}: {elapsed:.1f} s"


# ------------------------------------------------------------ round 2

DEFINITION = "Сторона: ТОВ «Альфа{h}Гарант» (далі — Страховик) уклала договір."
HYPHENS = {
    "u2010": "‐",
    "u2011": "‑",
    "u2013": "–",
    "u2212": "−",
    "uff0d": "－",
}


@pytest.mark.parametrize("mark", sorted(HYPHENS))
def test_review2_unicode_hyphen_variant_is_masked_and_grouped_with_definition(
    make_client: Make, mark: str
) -> None:
    later = f"Альфа{HYPHENS[mark]}Гарант"

    data = detect(make_client(), DEFINITION.format(h="-"), f"1. Платіж {later} сплачено.")

    assert_masked(data, later, only_block=1)
    [org] = [
        e for e in covering(data, "Альфа-Гарант", {"ORG"}) if any(sp[0] == 0 for sp in e["spans"])
    ]
    assert any(sp[0] == 1 for sp in org["spans"])


@pytest.mark.parametrize("mark", ["‑", "‐", "–"])
def test_review2_definition_with_unicode_hyphen_masks_later_ascii_hyphen(
    make_client: Make, mark: str
) -> None:
    data = detect(make_client(), DEFINITION.format(h=mark), "1. Платіж Альфа-Гарант сплачено.")

    assert_masked(data, "Альфа-Гарант", only_block=1)


def test_review2_later_mention_wrapped_at_its_own_hyphen_is_one_span(make_client: Make) -> None:
    data = detect(
        make_client(), DEFINITION.format(h="-"), "1. Платіж Альфа-\nГарант сплачено вчасно."
    )

    assert_masked(data, "Альфа-\nГарант", only_block=1)
    assert any(
        sp[0] == 1 and "Альфа" in span_text(data, sp) and "Гарант" in span_text(data, sp)
        for e in data["entities"]
        for sp in e["spans"]
    )


def test_review2_bare_idn_domain_is_masked_as_url(make_client: Make) -> None:
    data = detect(make_client(), "Сайт alfa-garant.укр містить умови.")

    assert_masked(data, "alfa-garant.укр")
    assert covering(data, "alfa-garant.укр", {"URL"})


def test_review2_surname_comma_given_name_each_part_is_masked(make_client: Make) -> None:
    data = detect(
        make_client(), "The seller is represented by DOE, JANE, acting under the Charter."
    )

    assert_masked(data, "DOE")
    assert_masked(data, "JANE")


def test_review2_space_instead_of_hyphen_after_hyphenated_definition_is_masked(
    make_client: Make,
) -> None:
    data = detect(make_client(), DEFINITION.format(h="-"), "1. Платіж Альфа Гарант сплачено.")

    assert_masked(data, "Альфа Гарант", only_block=1)
