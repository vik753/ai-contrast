"""S3-T1 review round 1 (PR #20): control characters and line breaks in plain text
(developer tests). Cc characters other than TAB and LF are removed and reported;
NEL, LS and PS become line breaks."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.extraction.model import ExtractionResult
from app.extraction.text import extract_text_file

CLAUSE = "Synthetic clause text that is plain and harmless. " * 4


def _extract(text: str) -> ExtractionResult:
    return extract_text_file(text.encode("utf-8"))


def _joined(result: ExtractionResult) -> str:
    return "\n\n".join(block.text for block in result.blocks)


def test_control_character_removed_and_counted() -> None:
    result = _extract(CLAUSE + "\x01x\x01")

    assert "\x01" not in _joined(result)
    assert [(r.reason, r.count, r.sample) for r in result.removed] == [
        ("control_character", 2, "U+0001")
    ]


# FF and VT become line feeds since S3-T2 (tests/test_docx_text_normalization.py).
@pytest.mark.parametrize("char", ["\x1b", "\x7f", "\x80", "\x9f"])
def test_other_cc_characters_removed(char: str) -> None:
    result = _extract(CLAUSE + char + "end")

    assert char not in _joined(result)
    assert _joined(result).endswith("end")
    assert result.removed[0].count == 1
    assert result.removed[0].sample == f"U+{ord(char):04X}"


def test_tab_and_line_feed_kept() -> None:
    result = _extract("Clause\tvalue\nnext line")

    assert _joined(result) == "Clause\tvalue\nnext line"
    assert result.removed == []


SEPARATORS = [chr(0x85), chr(0x2028), chr(0x2029)]  # NEL, LS, PS


@pytest.mark.parametrize("separator", SEPARATORS, ids=["nel", "ls", "ps"])
def test_unicode_line_breaks_become_line_feed(separator: str) -> None:
    result = _extract(f"Line A{separator}Line B{separator}{separator}Clause 2")

    assert [block.text for block in result.blocks] == ["Line A\nLine B", "Clause 2"]
    assert result.removed == []


def test_sample_lists_distinct_code_points_sorted() -> None:
    result = _extract(CLAUSE * 2 + "\x02\x01\x02\x01")

    assert result.removed[0].count == 4
    assert result.removed[0].sample == "U+0001 U+0002"


def test_only_control_characters_and_space_is_no_text() -> None:
    with pytest.raises(Exception, match="no_text_extracted"):
        extract_text_file(b"   \x0c\x0c  " + b" " * 400)


def test_removed_reported_through_the_api(make_client: Callable[..., TestClient]) -> None:
    response = make_client().post(
        "/api/extract",
        content=(CLAUSE + "\x07").encode(),
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json()["removed"] == [
        {"reason": "control_character", "count": 1, "sample": "U+0007"}
    ]
