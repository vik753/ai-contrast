# ruff: noqa: RUF001 - look-alike characters are the point of these tests
"""S5b-T4 AC 1: the harness itself. A harness that cannot fail proves nothing."""

from __future__ import annotations

import json
import re

import pytest

from tests.canary.catalogue import BY_ID
from tests.canary.harness import (
    JSON_HEADERS,
    WireCapture,
    client,
    find_leaks,
    key,
    run_cell,
)

PLACEHOLDER = re.compile(r"\[A\.[A-Z_]+_[1-9][0-9]*\]")

# ------------------------------------------------------------------------------ matcher


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("Мирошниченко", "виплата МИРОШНИЧЕНКО сьогодні"),  # case
        ("Fairbanks", "Mr N. ＦＡＩＲＢＡＮＫＳ signs"),  # NFKC (full-width)
        ("Петренко", "Пeтрeнко І. І."),  # Latin e inside a Cyrillic word (skeleton)
        ("Петренко", "Петренко".replace("е", "e")),  # same, lower case
        ("UA113052990000026003345678901", "UA11 3052 9900 0002 6003 3456 7890 1"),  # spaces
        ("Левандовський", "Левандов\u200bський"),  # zero-width space
        ("Левандовський", "Левандов­ський"),  # soft hyphen
        ("Левандовський", "Левандовсь-\nкий"),  # line-end hyphen
        ("+380 67 555 41 82", "тел. 380-67-555-41-82"),  # separators
        ("Мирошниченко", "[A.PERSON_1]ко стверджує Мирошниченк"),  # partial mask: 11 of 12
        ("synytsia-mail", "Synytsia_Mail"),
    ],
)
def test_matcher_finds_variant(needle: str, haystack: str) -> None:
    assert find_leaks([needle], haystack) == [needle]


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("Мирошниченко", "виплата [A.PERSON_1] сьогодні"),
        ("Fairbanks", "Mr [A.PERSON_1] signs for [A.ORG_1]"),
        ("UA113052990000026003345678901", "рахунок [A.ACCOUNT_1]"),
        ("Теплобуд", "Послуги надає компанія, яка будує"),
    ],
)
def test_matcher_ignores_masked_and_unrelated_text(needle: str, haystack: str) -> None:
    assert find_leaks([needle], haystack) == []


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("Мельник", "Кадастровий номер земельної ділянки"),  # 'мельн' inside a word
        ("Кравець", "[A.ORG_6] діє як виконавець за договором"),  # 'авець' inside a word
        ("Коваль", "Страхувальник підписав"),  # 'вальн'/'льник' inside a word
        ("15-К/2031", "('docx', 'ok', 203.1257)"),  # timing digits in a log tuple
    ],
)
def test_matcher_ignores_fragment_inside_ordinary_word(needle: str, haystack: str) -> None:
    assert find_leaks([needle], haystack) == []


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("UA113052990000026003345678901", "рахунок [A.ACCOUNT_1]UA11305299000002600334"),
        ("UA113052990000026003345678901", "IBAN №UA11305299000002600334 вказано"),
        ("UA113052990000026003345678901", "рахунок-UA11305299000002600334"),
        ("UA113052990000026003345678901", "рахунок/UA11305299000002600334"),
        ("UA113052990000026003345678901", "рахунок:UA11305299000002600334"),
        ("UA113052990000026003345678901", "IBAN UA 113052990000026003345"),
        ("Левченко", "[A.PERSON_1]евченко підписав"),
        ("oleksandr.shevchenko@example.com", "[A.EMAIL_1]oleksandr.shevchenko@exa"),
        ("Мирошниченко", "Страхувальник:Мирошниченк"),
        ("Мирошниченко", "ПІБ(Мирошниченк)"),
    ],
)
def test_matcher_flags_partial_mask_after_placeholder_or_punctuation(
    needle: str, haystack: str
) -> None:
    assert find_leaks([needle], haystack) == [needle]


def test_matcher_still_flags_a_fragment_at_a_word_start() -> None:
    assert find_leaks(["Мельник"], "підписав Мельни та інші") == ["Мельник"]


def test_key_is_stable_and_alphanumeric_only() -> None:
    assert key("A-b\u200b c_1") == key("ａ B C 1") == "abc1"


# ----------------------------------------------------------- the pipeline can really fail


def test_unmasked_text_is_reported_as_a_leak() -> None:
    run = run_cell("txt", "body", "clean")
    needles = [n for c in run.canaries for n in c.needles]
    assert len(find_leaks(needles, run.block_text)) == len(needles)  # raw text: all leak
    assert find_leaks(needles, run.masked_text) == []  # masked text: none


def test_safety_check_refuses_a_document_that_was_not_masked() -> None:
    """The second line of defence: the raw clauses are rejected."""
    run = run_cell("txt", "body", "clean")
    raw_clauses = [
        {
            "id": c["id"],
            "text": "\n".join(run.segment["blocks"][i]["text"][s:e] for i, s, e in c["spans"]),
        }
        for c in run.segment["clauses"]
    ]
    payload = {**run.safety_payload, "clauses": raw_clauses, "acknowledged_unmasked": []}

    reply = client().post(
        "/api/safety-check",
        content=json.dumps(payload, ensure_ascii=False).encode(),
        headers=JSON_HEADERS,
    )

    assert reply.status_code == 422
    assert reply.json()["error"] == "unmasked_identifier"


def test_masked_text_uses_only_grammar_placeholders() -> None:
    run = run_cell("docx", "body", "clean")
    leftovers = PLACEHOLDER.sub("", run.masked_text)
    assert "[A." not in leftovers


def test_masked_text_is_numbered_per_class_without_gaps() -> None:
    run = run_cell("docx", "body", "clean")
    seen: dict[str, set[int]] = {}
    for cls, number in re.findall(r"\[A\.([A-Z_]+)_([1-9][0-9]*)\]", run.masked_text):
        seen.setdefault(cls, set()).add(int(number))
    assert seen
    for numbers in seen.values():
        assert numbers == set(range(1, len(numbers) + 1))


def test_canary_planted_in_one_cell_is_masked_in_that_cell_and_known_gap_is_not() -> None:
    run = run_cell("txt", "body", "all")
    assert find_leaks(BY_ID["uk-person-forms"].needles, run.masked_text) == []
    assert find_leaks(BY_ID["uk-org-one-word"].needles, run.masked_text) != []


# --------------------------------------------------------- stage 6 plug-in (wire capture)


def test_wire_capture_hook_is_clean_until_a_provider_records(wire_capture: WireCapture) -> None:
    run = run_cell("txt", "body", "clean")
    needles = [n for c in run.canaries for n in c.needles]
    assert wire_capture.leaks(needles) == []


def test_wire_capture_hook_reports_a_recorded_canary(wire_capture: WireCapture) -> None:
    wire_capture.record({"messages": [{"content": "Pay Мирошниченко С.О. now"}]})
    assert wire_capture.leaks(BY_ID["uk-person-forms"].needles) == ["Мирошниченк"]


def test_wire_capture_hook_accepts_masked_payload_of_the_pipeline(
    wire_capture: WireCapture,
) -> None:
    run = run_cell("docx", "body", "clean")
    wire_capture.record(run.safety_payload)
    needles = [n for c in run.canaries for n in c.needles]
    assert wire_capture.leaks(needles) == []
