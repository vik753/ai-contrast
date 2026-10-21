# ruff: noqa: RUF001 - Cyrillic letters are the point of these tests
"""S3-T1 review round 1 (PR #20): boundaries of the language rules (developer tests)."""

from __future__ import annotations

import pytest

from app.extraction.language import MIN_LETTERS, SIGNIFICANT_SHARE, detect_language

UK_LETTER = "і"  # a Ukrainian marker letter
PLAIN_CYRILLIC = "д"  # no marker: Ukrainian or Russian


def test_language_below_min_letters_is_unknown() -> None:
    assert detect_language("a" * (MIN_LETTERS - 1)) == "unknown"


def test_language_at_min_letters_is_detected() -> None:
    assert detect_language("a" * MIN_LETTERS) == "en"


def test_language_non_letters_do_not_count() -> None:
    assert detect_language("a" * (MIN_LETTERS - 1) + " 1234567890 .,;-") == "unknown"


def _latin_and_ukrainian(ukrainian: int, total: int = 100) -> str:
    return "a" * (total - ukrainian) + UK_LETTER * ukrainian


def test_language_second_language_at_significant_share_is_mixed() -> None:
    share = round(SIGNIFICANT_SHARE * 100)

    assert detect_language(_latin_and_ukrainian(share)) == "mixed"


def test_language_second_language_below_significant_share_is_ignored() -> None:
    share = round(SIGNIFICANT_SHARE * 100)

    assert detect_language(_latin_and_ukrainian(share - 1)) == "en"


def test_language_cyrillic_without_markers_is_unknown() -> None:
    assert detect_language(PLAIN_CYRILLIC * 50) == "unknown"


def test_language_cyrillic_without_markers_and_significant_latin_is_mixed() -> None:
    assert detect_language("a" * 50 + PLAIN_CYRILLIC * 50) == "mixed"


@pytest.mark.parametrize("cyrillic", [1, 10, 19])
def test_language_few_cyrillic_without_markers_stays_english(cyrillic: int) -> None:
    assert detect_language("a" * (100 - cyrillic) + PLAIN_CYRILLIC * cyrillic) == "en"
