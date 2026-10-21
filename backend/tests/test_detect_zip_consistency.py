"""S2-T1 review round 1 (PR #15): the detector reads a ZIP the same way as
Python ``zipfile`` (the stage 3 reader), stricter entry names, BOM rules.

Detection rules 3.1-3.3 and 5 in docs/agent/TASKS.md; threat model T4 3a, 3b.
Every fixture is built byte by byte in ``tests/zipbuild.py``.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from tests.test_detect import detect, kind, rejected_code
from tests.zipbuild import (
    DOCX_PARTS,
    ENGLISH_TEXT,
    RUSSIAN_TEXT,
    UKRAINIAN_TEXT,
    RawEntry,
    build_zip,
    docx_entries,
    fake_eocd_in_comment_archive,
    second_central_directory_archive,
    stored,
    zipfile_archive,
)

# --- 9. Parser differential --------------------------------------------------------------


def test_fixture_second_central_directory_is_a_real_differential() -> None:
    data, benign, evil = second_central_directory_archive()

    assert benign != evil
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == evil


def test_detect_second_central_directory_before_eocd_returns_archive_rejected() -> None:
    data, _, _ = second_central_directory_archive()

    assert rejected_code(data) == "archive_rejected"


def test_detect_gap_between_central_directory_and_eocd_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(), between_cd_and_eocd=b"\x00" * 46)

    assert rejected_code(data) == "archive_rejected"


def test_detect_one_byte_gap_before_eocd_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), between_cd_and_eocd=b"x")) == (
        "archive_rejected"
    )


@pytest.mark.parametrize("fake_comment", [b"", b"tail", b"PK"], ids=["exact", "tail", "pk"])
def test_fixture_fake_eocd_in_comment_is_a_real_differential(fake_comment: bytes) -> None:
    data, evil = fake_eocd_in_comment_archive(fake_comment=fake_comment)

    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == evil


@pytest.mark.parametrize("fake_comment", [b"", b"tail", b"PK"], ids=["exact", "tail", "pk"])
def test_detect_fake_eocd_and_directory_in_comment_returns_archive_rejected(
    fake_comment: bytes,
) -> None:
    data, _ = fake_eocd_in_comment_archive(fake_comment=fake_comment)

    assert rejected_code(data) == "archive_rejected"


@pytest.mark.parametrize(
    "signature",
    [b"PK\x05\x06", b"PK\x06\x06", b"PK\x06\x07"],
    ids=["eocd", "zip64-eocd", "zip64-locator"],
)
@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_detect_signature_in_archive_comment_returns_archive_rejected(
    signature: bytes, position: str
) -> None:
    filler = b"synthetic comment"
    comment = {
        "start": signature + filler,
        "middle": filler + signature + filler,
        "end": filler + signature,
    }[position]

    assert rejected_code(build_zip(docx_entries(), comment=comment)) == "archive_rejected"


def test_detect_parsed_entry_count_above_eocd_count_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), total_entries=2, disk_entries=2)) == (
        "archive_rejected"
    )


def test_detect_parsed_entry_count_below_eocd_count_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), total_entries=4, disk_entries=4)) == (
        "archive_rejected"
    )


def _valid_archives() -> dict[str, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.mkdir("word/media")
        for name, data in DOCX_PARTS:
            archive.writestr(name, data)
        archive.writestr("word/media/note.txt", b"synthetic")
    many = [*DOCX_PARTS, *((f"word/media/{i:03d}.txt", b"x" * i) for i in range(1, 60))]
    return {
        "deflated": zipfile_archive(list(DOCX_PARTS)),
        "stored": zipfile_archive(list(DOCX_PARTS), compression=zipfile.ZIP_STORED),
        "comment": zipfile_archive(list(DOCX_PARTS), comment=b"synthetic comment"),
        "directory": buffer.getvalue(),
        "many-entries": zipfile_archive(many),
        "styles": zipfile_archive(
            [*DOCX_PARTS, ("word/styles.xml", b"<w:styles/>" * 50), ("docProps/core.xml", b"<c/>")]
        ),
        "hand-built": build_zip(docx_entries()),
    }


VALID_CASES = sorted(_valid_archives())


@pytest.mark.parametrize("case", VALID_CASES)
def test_valid_archive_zipfile_and_detector_both_accept(case: str) -> None:
    data = _valid_archives()[case]

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
    assert "word/document.xml" in names
    assert detect(data) == kind("DOCX")


# --- 10. Entry names ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data"),
    [
        pytest.param("word/./document2.xml", b"x", id="dot-segment"),
        pytest.param("./word/document2.xml", b"x", id="leading-dot-segment"),
        pytest.param("word//document2.xml", b"x", id="empty-segment"),
        pytest.param("word/document2.xml.", b"x", id="trailing-dot"),
        pytest.param("word./document2.xml", b"x", id="dir-trailing-dot"),
        pytest.param("word/media/", b"x", id="trailing-slash-non-empty"),
        pytest.param("word/зображення.xml", b"x", id="non-ascii-utf8-flag"),
        pytest.param(b"word/\x80\x81.xml", b"x", id="non-ascii-cp437"),
        pytest.param(b"word/a\x01.xml", b"x", id="control-0x01"),
        pytest.param(b"word/a\x1f.xml", b"x", id="control-0x1f"),
        pytest.param(b"word/a\x7f.xml", b"x", id="del-0x7f"),
        pytest.param(b"word/a\tb.xml", b"x", id="tab"),
        pytest.param(b"word/a\nb.xml", b"x", id="newline"),
        pytest.param("C:/evil.xml", b"x", id="drive-letter-slash"),
        pytest.param("c:evil.xml", b"x", id="drive-letter-relative"),
        pytest.param("Z:/word/document2.xml", b"x", id="drive-letter-upper"),
    ],
)
def test_detect_bad_entry_name_returns_archive_rejected(name: str | bytes, data: bytes) -> None:
    entry = RawEntry(name=name, data=data)

    assert rejected_code(build_zip(docx_entries(entry))) == "archive_rejected"


def test_detect_utf8_flag_on_ascii_name_rejected_only_if_name_not_ascii() -> None:
    # The flag alone does not make an ASCII name invalid.
    entry = RawEntry(name="word/media/note.txt", data=b"x", flags=0x0800)

    assert detect(build_zip(docx_entries(entry))) == kind("DOCX")


def test_detect_directory_entry_with_size_zero_returns_docx() -> None:
    assert detect(build_zip(docx_entries(stored("word/")))) == kind("DOCX")


def test_detect_nested_directory_entries_with_size_zero_return_docx() -> None:
    data = build_zip(docx_entries(stored("word/media/"), stored("word/media/img/")))

    assert detect(data) == kind("DOCX")


def test_detect_dot_inside_segment_returns_docx() -> None:
    # Only a whole "." or ".." segment, or a segment ending in ".", is rejected.
    data = build_zip(docx_entries(stored("word/.hidden.v1.xml", b"x"), stored("_rels/a..b", b"x")))

    assert detect(data) == kind("DOCX")


def test_detect_name_with_space_and_punctuation_returns_docx() -> None:
    name = "word/media/a b-c_d~e!(1)[2]{3}+=@#$&',;.txt"

    assert detect(build_zip(docx_entries(stored(name, b"x")))) == kind("DOCX")


def test_detect_percent_encoded_name_not_rejected_in_stage_2() -> None:
    # Stage 3 rule, not stage 2: the OPC part-name grammar (ECMA-376 Part 2
    # 6.2.2) forbids percent-encoded unreserved characters, and duplicates
    # are checked after canonical decoding. Here "%64" is printable ASCII.
    data = build_zip(docx_entries(stored("word/%64ocument.xml", b"<w/>")))

    assert detect(data) == kind("DOCX")


# --- 11. BOM rules ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\xef\xbb\xbf" + b"synthetic\x00binary", id="utf8-bom-nul"),
        pytest.param(b"\xef\xbb\xbf" + b"\x01" * 50 + b"a" * 100, id="utf8-bom-controls"),
        pytest.param(b"\xef\xbb\xbf" + bytes(range(256)) * 4, id="utf8-bom-binary"),
    ],
)
def test_detect_utf8_bom_with_binary_returns_unsupported_type(data: bytes) -> None:
    assert rejected_code(data) == "unsupported_type"


@pytest.mark.parametrize(
    "text", [ENGLISH_TEXT, UKRAINIAN_TEXT, RUSSIAN_TEXT], ids=["en", "uk", "ru"]
)
def test_detect_utf8_bom_with_clean_text_returns_text(text: str) -> None:
    assert detect(b"\xef\xbb\xbf" + text.encode("utf-8")) == kind("TEXT")


def test_detect_utf8_bom_only_returns_text() -> None:
    assert detect(b"\xef\xbb\xbf") == kind("TEXT")


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\xff\xfe" + UKRAINIAN_TEXT.encode("utf-16-le") + b"x", id="le-odd"),
        pytest.param(b"\xfe\xff" + RUSSIAN_TEXT.encode("utf-16-be") + b"x", id="be-odd"),
        pytest.param(b"\xff\xfe\x41", id="le-three-bytes"),
    ],
)
def test_detect_utf16_bom_with_odd_length_returns_unsupported_type(data: bytes) -> None:
    assert len(data) % 2 == 1

    assert rejected_code(data) == "unsupported_type"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\xff\xfe" + UKRAINIAN_TEXT.encode("utf-16-le"), id="le-even"),
        pytest.param(b"\xfe\xff" + RUSSIAN_TEXT.encode("utf-16-be"), id="be-even"),
        pytest.param(b"\xff\xfe", id="le-bom-only"),
    ],
)
def test_detect_utf16_bom_with_even_length_returns_text(data: bytes) -> None:
    assert len(data) % 2 == 0

    assert detect(data) == kind("TEXT")
