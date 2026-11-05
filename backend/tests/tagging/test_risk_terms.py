"""S8-T1 AC2: risk-term scan (ADR 0018 point 4)."""
# ruff: noqa: PT018, PLC0415
# ruff: noqa: RUF001

from __future__ import annotations

import pytest

from app.tagging.risk_terms import RISK_TERMS_VERSION, scan_risk

EN = [
    "penalty",
    "fine",
    "forfeit",
    "exclusion",
    "not covered",
    "waive",
    "unilateral",
    "terminate",
    "indemnify",
    "liquidated damages",
]
UK = [
    "штраф",
    "пеня",
    "неустойка",
    "не відшкодовується",
    "виключення",
    "в односторонньому порядку",
    "відмова",
]
RU = [
    "штраф",
    "пеня",
    "неустойка",
    "не возмещается",
    "исключение",
    "в одностороннем порядке",
    "отказ",
]


@pytest.mark.parametrize("term", EN)
def test_scan_risk_english_terms_hit(term: str) -> None:
    text = f"The tenant agrees to a {term} under this clause."
    hits = scan_risk(text)
    assert hits
    start, end = hits[0]
    assert start == text.index(term.split(maxsplit=1)[0]) and end > start


@pytest.mark.parametrize("term", UK)
def test_scan_risk_ukrainian_terms_hit(term: str) -> None:
    assert scan_risk(f"Сторона сплачує {term} за цим пунктом.")


@pytest.mark.parametrize("term", RU)
def test_scan_risk_russian_terms_hit(term: str) -> None:
    assert scan_risk(f"Сторона оплачивает {term} по этому пункту.")


def test_scan_risk_plain_text_has_no_hit() -> None:
    assert scan_risk("The parties meet on Tuesday to discuss the weather.") == []
    assert scan_risk("") == []


def test_scan_risk_stem_matches_only_at_word_start() -> None:
    assert scan_risk("We define and confine the scope.") == []
    assert scan_risk("Fines apply.")


def test_scan_risk_case_insensitive_and_homoglyph() -> None:
    assert scan_risk("PENALTY of 5%")
    assert scan_risk("A pеnalty of 5%")  # Cyrillic e
    assert scan_risk("ШТРАФ 5%")


def test_scan_risk_hits_sorted_and_within_text() -> None:
    text = "A penalty applies. The seller may terminate. Fine."
    hits = scan_risk(text)
    assert len(hits) >= 3
    assert hits == sorted(hits)
    assert all(0 <= s < e <= len(text) for s, e in hits)


def test_scan_risk_long_input_is_fast() -> None:
    import time

    start = time.process_time()
    scan_risk("pena " * 200_000 + "x" * 500_000)
    assert time.process_time() - start < 5


def test_risk_terms_version_is_a_string() -> None:
    assert isinstance(RISK_TERMS_VERSION, str) and RISK_TERMS_VERSION
