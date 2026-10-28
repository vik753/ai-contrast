# ruff: noqa: RUF001
"""S5-T1b follow-up: line breaks are normalized inside the shared cleaner."""

from __future__ import annotations

import pytest

from app.textclean import clean_text


@pytest.mark.parametrize("brk", ["\u0085", " ", " ", "\r\n", "\r", "\x0b", "\x0c"])
def test_line_breaks_become_lf(brk: str) -> None:
    result = clean_text(f"a{brk}b")

    assert result.text == "a\nb"
    assert result.removed == []
    assert clean_text(result.text).text == result.text
