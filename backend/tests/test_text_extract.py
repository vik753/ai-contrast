# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""S3-T1 AC4 and AC6: plain-text extraction (``extract_text_file``, pure; T4).

Decoding: strict UTF-8 (BOM optional), strict UTF-16 with BOM, otherwise
strict CP1251; failure -> ``text_decoding_failed``. The control-character rule
of detection runs again on the whole text and fails closed. Newlines are
normalized to ``\\n``; blocks are split by blank lines; ``part`` is ``body``.
Caps fail closed: ``too_much_text`` (characters, blocks), ``no_text_extracted``.

Assumption (see the test report): the whole-text control-character failure
uses the code ``text_decoding_failed``.
"""

from __future__ import annotations

import pytest

from app.extraction.model import ExtractionError, ExtractionResult
from app.extraction.text import extract_text_file
from tests.helpers import new_canary

UK = "Договір надання послуг (тестові дані).\n\nОплата протягом 30 днів, ґрунт і її межі.\n"
RU = "Договор оказания услуг (тестовые данные).\n\nОплата в течение 30 дней, счёт выставляется.\n"
EN = "Service agreement (synthetic test data).\n\nThe Client pays within 30 days.\n"

DEFAULT_MAX_TEXT_CHARS = 2_000_000
DEFAULT_MAX_BLOCKS = 20_000
DETECTION_WINDOW = 64 * 1024


def _texts(result: ExtractionResult) -> list[str]:
    return [block.text for block in result.blocks]


def _code(data: bytes) -> str:
    with pytest.raises(ExtractionError) as info:
        extract_text_file(data)
    return info.value.code


# --- Result shape ------------------------------------------------------------------------


def test_text_result_has_text_kind_and_byte_count() -> None:
    data = EN.encode()

    result = extract_text_file(data)

    assert (result.kind, result.bytes) == ("text", len(data))


def test_text_result_has_no_pages_ocr_removed_or_warnings() -> None:
    result = extract_text_file(EN.encode())

    assert result.pages is None
    assert result.ocr_pages == []
    assert result.removed == []
    assert result.warnings == []


def test_text_blocks_are_body_without_page() -> None:
    result = extract_text_file(EN.encode())

    assert result.blocks
    assert all(block.part == "body" for block in result.blocks)
    assert all(block.page is None for block in result.blocks)


# --- Decoding ----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [UK, RU, EN], ids=["uk", "ru", "en"])
def test_text_utf8_without_bom_decoded(text: str) -> None:
    assert "\n\n".join(_texts(extract_text_file(text.encode("utf-8")))) == text.strip()


def test_text_utf8_with_bom_decoded_and_bom_removed() -> None:
    result = extract_text_file(b"\xef\xbb\xbf" + UK.encode("utf-8"))

    assert "\n\n".join(_texts(result)) == UK.strip()
    assert "﻿" not in "".join(_texts(result))


@pytest.mark.parametrize(
    ("bom", "codec"),
    [(b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")],
    ids=["le", "be"],
)
def test_text_utf16_with_bom_decoded(bom: bytes, codec: str) -> None:
    result = extract_text_file(bom + UK.encode(codec))

    assert "\n\n".join(_texts(result)) == UK.strip()
    assert "﻿" not in "".join(_texts(result))


@pytest.mark.parametrize("text", [UK, RU], ids=["uk", "ru"])
def test_text_cp1251_decoded(text: str) -> None:
    assert "\n\n".join(_texts(extract_text_file(text.encode("cp1251")))) == text.strip()


def test_text_byte_count_is_raw_input_length_for_cp1251() -> None:
    data = UK.encode("cp1251")

    assert extract_text_file(data).bytes == len(data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\xff\xfe" + "Договір ".encode("utf-16-le") + b"\x00\xd8A\x00", id="le-lone"),
        pytest.param(b"\xfe\xff" + "Договір ".encode("utf-16-be") + b"\xd8\x00\x00A", id="be-lone"),
        pytest.param(b"\xff\xfe" + "Договір".encode("utf-16-le") + b"A", id="le-odd-length"),
    ],
)
def test_text_invalid_utf16_rejected(data: bytes) -> None:
    assert _code(data) == "text_decoding_failed"


def test_text_neither_utf8_nor_cp1251_rejected() -> None:
    # 0x98 is invalid UTF-8 here and undefined in CP1251.
    assert _code("Договір ".encode("cp1251") + b"\x98 30 days") == "text_decoding_failed"


def test_text_decoding_error_never_contains_input() -> None:
    canary = new_canary()

    with pytest.raises(ExtractionError) as info:
        extract_text_file(canary.encode() + b" \x98")

    assert canary not in str(info.value)
    assert canary not in repr(info.value.args)


# --- Control characters on the whole text (fail closed) ---------------------------------


def _clean_prefix() -> bytes:
    line = b"Synthetic clause text that is plain and harmless.\n"
    return line * (DETECTION_WINDOW // len(line) + 10)  # longer than the detection window


def test_text_many_controls_after_detection_window_rejected() -> None:
    data = _clean_prefix() + b"\x01" * 5000  # above 1 % of the whole text

    assert _code(data) == "text_decoding_failed"


def test_text_nul_after_detection_window_rejected() -> None:
    data = _clean_prefix() + b"\x00" * 5000

    assert _code(data) == "text_decoding_failed"


def test_text_many_controls_in_utf16_rejected() -> None:
    data = b"\xff\xfe" + ("Договір. " + "\x02" * 50).encode("utf-16-le")

    assert _code(data) == "text_decoding_failed"


def test_text_few_controls_accepted() -> None:
    data = b"Synthetic clause text. " * 50 + b"\x01"  # far below 1 %

    assert extract_text_file(data).blocks


def test_text_tabs_and_form_feeds_do_not_count_as_controls() -> None:
    data = b"Clause\t\t\t\tvalue\f\f\f\f\n" * 20

    assert extract_text_file(data).blocks


# --- Newlines and blocks -----------------------------------------------------------------


def test_text_newlines_normalized_inside_block() -> None:
    assert _texts(extract_text_file(b"Line A\r\nLine B\rLine C\nLine D")) == [
        "Line A\nLine B\nLine C\nLine D"
    ]


def test_text_blocks_split_by_blank_line() -> None:
    assert _texts(extract_text_file(b"Clause 1\n\nClause 2")) == ["Clause 1", "Clause 2"]


def test_text_blocks_split_by_crlf_blank_line() -> None:
    assert _texts(extract_text_file(b"Clause 1\r\n\r\nClause 2\r\n")) == ["Clause 1", "Clause 2"]


def test_text_blocks_split_by_cr_blank_line() -> None:
    assert _texts(extract_text_file(b"Clause 1\r\rClause 2")) == ["Clause 1", "Clause 2"]


def test_text_several_blank_lines_make_no_empty_block() -> None:
    assert _texts(extract_text_file(b"Clause 1\n\n\n\n\nClause 2")) == ["Clause 1", "Clause 2"]


def test_text_leading_and_trailing_blank_lines_make_no_empty_block() -> None:
    assert _texts(extract_text_file(b"\n\n\nClause 1\n\nClause 2\n\n\n")) == [
        "Clause 1",
        "Clause 2",
    ]


def test_text_no_block_contains_carriage_return() -> None:
    result = extract_text_file(b"A\r\nB\r\n\r\nC\rD\r\r\rE")

    assert all("\r" not in text for text in _texts(result))


# --- Caps (AC6) --------------------------------------------------------------------------


def test_text_at_char_cap_accepted() -> None:
    result = extract_text_file(b"a" * DEFAULT_MAX_TEXT_CHARS)

    assert sum(len(text) for text in _texts(result)) == DEFAULT_MAX_TEXT_CHARS


def test_text_above_char_cap_rejected() -> None:
    assert _code(b"a" * (DEFAULT_MAX_TEXT_CHARS + 1)) == "too_much_text"


def test_text_char_cap_counts_characters_not_bytes() -> None:
    # 1,500,000 Cyrillic characters are 3,000,000 UTF-8 bytes but stay under the cap.
    result = extract_text_file(("д" * 1_500_000).encode("utf-8"))

    assert sum(len(text) for text in _texts(result)) == 1_500_000


def test_text_at_block_cap_accepted() -> None:
    assert len(extract_text_file(b"x\n\n" * DEFAULT_MAX_BLOCKS).blocks) == DEFAULT_MAX_BLOCKS


def test_text_above_block_cap_rejected() -> None:
    assert _code(b"x\n\n" * (DEFAULT_MAX_BLOCKS + 1)) == "too_much_text"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\xef\xbb\xbf", id="utf8-bom-only"),
        pytest.param(b"\xff\xfe", id="utf16le-bom-only"),
        pytest.param(b"\xfe\xff", id="utf16be-bom-only"),
    ],
)
def test_text_zero_characters_rejected(data: bytes) -> None:
    assert _code(data) == "no_text_extracted"


def test_text_whitespace_only_rejected() -> None:
    assert _code(b"\n \n\t\n\r\n  ") == "no_text_extracted"
