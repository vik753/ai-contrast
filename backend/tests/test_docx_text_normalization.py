"""S3-T2 AC8: text normalization shared by plain text and DOCX.

Form feed (FF) and vertical tab (VT) become ``\\n`` (S3-T1 follow-up from the
security delta review of PR #20: words must not run together). The Cc rule of
S3-T1 (other control characters removed and reported as ``control_character``;
NEL, LS and PS become ``\\n``) also applies to DOCX text.

XML 1.0 cannot carry FF, VT or other C0 controls in ``w:t``, so the DOCX side is
tested with C1 controls and NEL. Must fail before the implementation exists.
"""

from __future__ import annotations

import pytest

from app.extraction.text import extract_text_file
from tests.docxbuild import CLAUSE, body_docx, p, para, r
from tests.docxrun import extract, joined, reasons

# Long enough that one control character stays under the 1 % rule of detection.
LONG = f"{CLAUSE} {CLAUSE} {CLAUSE}"

# --- Plain text: FF and VT ---------------------------------------------------------------------


@pytest.mark.parametrize("char", ["\x0c", "\x0b"], ids=["ff", "vt"])
def test_text_ff_vt_become_line_feed(char: str) -> None:
    result = extract_text_file(f"{LONG}{char}Clause two.".encode())

    assert [b.text for b in result.blocks] == [f"{LONG}\nClause two."]


@pytest.mark.parametrize("char", ["\x0c", "\x0b"], ids=["ff", "vt"])
def test_text_ff_vt_not_reported_as_removed(char: str) -> None:
    result = extract_text_file(f"{LONG}{char}Clause two.".encode())

    assert result.removed == []


def test_text_ff_between_words_keeps_words_apart() -> None:
    result = extract_text_file(f"{CLAUSE} Payment\x0cterms apply.".encode())

    assert "Paymentterms" not in "\n".join(b.text for b in result.blocks)


def test_text_double_ff_splits_blocks() -> None:
    # Two FF become a blank line: a block boundary, like any blank line.
    result = extract_text_file(f"{CLAUSE}\x0c\x0cClause two.".encode())

    assert [b.text for b in result.blocks] == [CLAUSE, "Clause two."]


def test_text_other_controls_still_removed() -> None:
    result = extract_text_file(f"{LONG}\x1bend".encode())

    assert reasons(result) == {"control_character": 1}


# --- DOCX: the same rule -----------------------------------------------------------------------


def test_docx_nel_becomes_line_feed() -> None:
    result = extract(body_docx(p(r("Line A\u0085Line B"))))

    assert joined(result) == "Line A\nLine B"


@pytest.mark.parametrize("char", ["\u2028", "\u2029"], ids=["ls", "ps"])
def test_docx_unicode_separators_become_line_feed(char: str) -> None:
    result = extract(body_docx(p(r(f"Line A{char}Line B"))))

    assert joined(result) == "Line A\nLine B"


@pytest.mark.parametrize("char", ["\u0080", "\u009b", "\u009f"])
def test_docx_c1_control_removed_and_reported(char: str) -> None:
    result = extract(body_docx(para(CLAUSE), p(r(f"Clause{char} two."))))

    assert char not in joined(result)
    assert "control_character" in reasons(result)
