"""S2-T1 AC2 and AC7: file type detection by magic bytes and ZIP structure checks.

Tests the pure function ``app.extraction.detect.detect_kind`` against the
detection rules in docs/agent/TASKS.md (Stage 2). Every fixture is built in
memory (see ``tests/zipbuild.py``). Threats: T4 (malicious files), T3.

The module under test is imported inside the tests, so that before the
implementation exists each test fails on its own with ``ModuleNotFoundError``
instead of breaking the collection of the whole test suite.
"""

from __future__ import annotations

import dataclasses
import importlib
import io
import zipfile
from types import ModuleType
from typing import Any

import pytest

from tests.helpers import new_marker
from tests.zipbuild import (
    CDH_SIG,
    DOCX_PARTS,
    ENGLISH_TEXT,
    FLAG_ENCRYPTED,
    GIF87_SAMPLE,
    GIF89_SAMPLE,
    JPEG_SAMPLE,
    OLE2_SAMPLE,
    PDF_SAMPLE,
    PNG_SAMPLE,
    RTF_SAMPLE,
    RUSSIAN_TEXT,
    TIFF_BE_SAMPLE,
    TIFF_LE_SAMPLE,
    UKRAINIAN_TEXT,
    WEBP_SAMPLE,
    RawEntry,
    build_zip,
    docx_entries,
    fake_deflated,
    minimal_docx,
    stored,
    zipfile_archive,
)

MIB = 1024 * 1024
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_UNCOMPRESSED = 100 * MIB
DEFAULT_MAX_RATIO = 200

DETECTION_CODES = {
    "empty_file",
    "unsupported_type",
    "legacy_office_unsupported",
    "pages_unsupported",
    "archive_rejected",
}


def _module() -> ModuleType:
    return importlib.import_module("app.extraction.detect")


def limits(
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED,
    max_ratio: int = DEFAULT_MAX_RATIO,
) -> Any:
    return _module().ZipLimits(
        max_entries=max_entries,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_ratio=max_ratio,
    )


def detect(data: bytes, **limit_overrides: int) -> Any:
    return _module().detect_kind(data, limits=limits(**limit_overrides))


def kind(name: str) -> Any:
    return getattr(_module().FileKind, name)


def rejected_code(data: bytes, **limit_overrides: int) -> str:
    """Run detection and return the ``DetectionError.code``. Fails if it returns."""
    module = _module()
    with pytest.raises(module.DetectionError) as info:
        module.detect_kind(data, limits=limits(**limit_overrides))
    code = info.value.code
    assert isinstance(code, str)
    return code


# --- Fixture sanity: the hand-built archives are valid ZIPs ------------------


def test_fixture_build_zip_docx_is_valid_for_zipfile() -> None:
    data = build_zip(docx_entries())

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == [name for name, _ in DOCX_PARTS]


def test_fixture_build_zip_with_comment_is_valid_for_zipfile() -> None:
    data = build_zip(docx_entries(), comment=b"synthetic comment")

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert archive.comment == b"synthetic comment"


# --- Public interface ---------------------------------------------------------


def test_file_kind_values_are_pdf_docx_text() -> None:
    file_kind = _module().FileKind

    assert {member.value for member in file_kind} == {"pdf", "docx", "text"}
    assert file_kind.PDF == "pdf"
    assert file_kind.DOCX == "docx"
    assert file_kind.TEXT == "text"


def test_detection_error_is_exception_with_code() -> None:
    module = _module()

    assert issubclass(module.DetectionError, Exception)


def test_zip_limits_is_frozen_dataclass_with_three_fields() -> None:
    value = limits()

    assert dataclasses.is_dataclass(value)
    assert {f.name for f in dataclasses.fields(value)} == {
        "max_entries",
        "max_uncompressed_bytes",
        "max_ratio",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.max_entries = 1


def test_detect_kind_limits_is_keyword_only() -> None:
    module = _module()

    with pytest.raises(TypeError):
        module.detect_kind(PDF_SAMPLE, limits())


# --- Rule 1, 2, 4: signatures -------------------------------------------------


def test_detect_pdf_signature_returns_pdf() -> None:
    assert detect(PDF_SAMPLE) == kind("PDF")


def test_detect_pdf_signature_only_returns_pdf() -> None:
    assert detect(b"%PDF-") == kind("PDF")


def test_detect_pdf_signature_not_at_offset_zero_is_not_pdf() -> None:
    assert detect(b"\n" + PDF_SAMPLE) != kind("PDF")


def test_detect_ole2_returns_legacy_office_unsupported() -> None:
    assert rejected_code(OLE2_SAMPLE) == "legacy_office_unsupported"


@pytest.mark.parametrize(
    "sample",
    [
        pytest.param(PNG_SAMPLE, id="png"),
        pytest.param(JPEG_SAMPLE, id="jpeg"),
        pytest.param(GIF87_SAMPLE, id="gif87a"),
        pytest.param(GIF89_SAMPLE, id="gif89a"),
        pytest.param(TIFF_LE_SAMPLE, id="tiff-le"),
        pytest.param(TIFF_BE_SAMPLE, id="tiff-be"),
        pytest.param(WEBP_SAMPLE, id="riff-webp"),
        pytest.param(RTF_SAMPLE, id="rtf"),
    ],
)
def test_detect_image_or_rtf_signature_returns_unsupported_type(sample: bytes) -> None:
    assert rejected_code(sample) == "unsupported_type"


# --- Rule 5: plain text -------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(ENGLISH_TEXT.encode("utf-8"), id="utf8-english"),
        pytest.param(UKRAINIAN_TEXT.encode("utf-8"), id="utf8-ukrainian"),
        pytest.param(RUSSIAN_TEXT.encode("utf-8"), id="utf8-russian"),
        pytest.param(b"\xef\xbb\xbf" + ENGLISH_TEXT.encode("utf-8"), id="utf8-bom"),
        pytest.param(b"\xff\xfe" + UKRAINIAN_TEXT.encode("utf-16-le"), id="utf16-le-bom"),
        pytest.param(b"\xfe\xff" + RUSSIAN_TEXT.encode("utf-16-be"), id="utf16-be-bom"),
        pytest.param(UKRAINIAN_TEXT.encode("cp1251"), id="cp1251-ukrainian"),
        pytest.param(RUSSIAN_TEXT.encode("cp1251"), id="cp1251-russian"),
        pytest.param(b"x", id="one-byte"),
        pytest.param(b"PK is not a zip signature on its own.\n", id="starts-with-pk-text"),
    ],
)
def test_detect_plain_text_returns_text(data: bytes) -> None:
    assert detect(data) == kind("TEXT")


def test_detect_utf16_le_bom_with_nul_bytes_returns_text() -> None:
    data = b"\xff\xfe" + ("A" * 200).encode("utf-16-le")
    assert b"\x00" in data

    assert detect(data) == kind("TEXT")


def test_detect_text_with_allowed_controls_only_returns_text() -> None:
    data = b"a\tb\nc\rd\fe" * 500  # 4 of 9 bytes are TAB, LF, CR or FF

    assert detect(data) == kind("TEXT")


def test_detect_binary_with_nul_returns_unsupported_type() -> None:
    assert rejected_code(b"synthetic text with a\x00nul byte") == "unsupported_type"


def test_detect_nul_after_first_64_kib_returns_text() -> None:
    data = b"a" * 65536 + b"\x00" + b"b" * 100

    assert detect(data) == kind("TEXT")


def test_detect_nul_at_last_byte_of_first_64_kib_returns_unsupported_type() -> None:
    data = b"a" * 65535 + b"\x00" + b"b" * 100

    assert rejected_code(data) == "unsupported_type"


def test_detect_control_chars_above_one_percent_returns_unsupported_type() -> None:
    data = b"\x01" * 11 + b"a" * 989  # 1.1 %

    assert rejected_code(data) == "unsupported_type"


def test_detect_control_chars_at_one_percent_returns_text() -> None:
    data = b"\x01" * 10 + b"a" * 990  # exactly 1 %, not more

    assert detect(data) == kind("TEXT")


def test_detect_many_mixed_control_chars_returns_unsupported_type() -> None:
    data = bytes(range(1, 32)) * 50 + ENGLISH_TEXT.encode("utf-8")

    assert rejected_code(data) == "unsupported_type"


def test_detect_control_chars_after_first_64_kib_return_text() -> None:
    data = b"a" * 65536 + b"\x01" * 5000

    assert detect(data) == kind("TEXT")


def test_detect_empty_zip_without_local_header_returns_unsupported_type() -> None:
    # An empty archive is only an EOCD record ("PK\x05\x06" and NUL bytes).
    data = zipfile_archive([])

    assert rejected_code(data) == "unsupported_type"


# --- Rule 3.5: ZIP classification by names ---------------------------------------


def test_detect_minimal_docx_from_zipfile_returns_docx() -> None:
    assert detect(minimal_docx()) == kind("DOCX")


def test_detect_stored_docx_returns_docx() -> None:
    assert detect(build_zip(docx_entries())) == kind("DOCX")


def test_detect_docx_with_archive_comment_returns_docx() -> None:
    assert detect(build_zip(docx_entries(), comment=b"synthetic comment")) == kind("DOCX")


def test_detect_docx_with_empty_directory_entry_returns_docx() -> None:
    assert detect(build_zip(docx_entries(stored("word/media/")))) == kind("DOCX")


def test_detect_docx_with_utf8_name_returns_docx() -> None:
    assert detect(build_zip(docx_entries(stored("word/media/зображення.txt", b"x")))) == kind(
        "DOCX"
    )


def test_detect_xlsx_like_archive_returns_unsupported_type() -> None:
    data = build_zip(
        [
            stored("[Content_Types].xml", b"<Types/>"),
            stored("_rels/.rels", b"<Relationships/>"),
            stored("xl/workbook.xml", b"<workbook/>"),
        ]
    )

    assert rejected_code(data) == "unsupported_type"


def test_detect_pptx_like_archive_returns_unsupported_type() -> None:
    data = build_zip(
        [
            stored("[Content_Types].xml", b"<Types/>"),
            stored("_rels/.rels", b"<Relationships/>"),
            stored("ppt/presentation.xml", b"<presentation/>"),
        ]
    )

    assert rejected_code(data) == "unsupported_type"


def test_detect_docx_with_extra_xl_part_returns_unsupported_type() -> None:
    data = build_zip(docx_entries(stored("xl/workbook.xml", b"<workbook/>")))

    assert rejected_code(data) == "unsupported_type"


def test_detect_docx_with_extra_ppt_part_returns_unsupported_type() -> None:
    data = build_zip(docx_entries(stored("ppt/presentation.xml", b"<presentation/>")))

    assert rejected_code(data) == "unsupported_type"


def test_detect_odf_archive_returns_unsupported_type() -> None:
    data = build_zip(
        [
            stored("mimetype", b"application/vnd.oasis.opendocument.text"),
            stored("content.xml", b"<office:document-content/>"),
            stored("META-INF/manifest.xml", b"<manifest:manifest/>"),
        ]
    )

    assert rejected_code(data) == "unsupported_type"


def test_detect_pages_like_archive_returns_pages_unsupported() -> None:
    data = build_zip(
        [
            stored("Index/Document.iwa", b"\x01\x02synthetic"),
            stored("Metadata/Properties.plist", b"<plist/>"),
            stored("preview.jpg", b"\xff\xd8\xff"),
        ]
    )

    assert rejected_code(data) == "pages_unsupported"


def test_detect_pages_archive_with_docx_parts_returns_pages_unsupported() -> None:
    data = build_zip(docx_entries(stored("Index/Document.iwa", b"synthetic")))

    assert rejected_code(data) == "pages_unsupported"


def test_detect_generic_zip_returns_unsupported_type() -> None:
    data = zipfile_archive([("readme.txt", b"synthetic")])

    assert rejected_code(data) == "unsupported_type"


def test_detect_zip_without_content_types_returns_unsupported_type() -> None:
    data = build_zip(
        [stored("_rels/.rels", b"<Relationships/>"), stored("word/document.xml", b"<w/>")]
    )

    assert rejected_code(data) == "unsupported_type"


def test_detect_zip_without_root_rels_returns_unsupported_type() -> None:
    data = build_zip(
        [stored("[Content_Types].xml", b"<Types/>"), stored("word/document.xml", b"<w/>")]
    )

    assert rejected_code(data) == "unsupported_type"


# --- Rule 3.1: EOCD -------------------------------------------------------------


def test_detect_local_header_signature_without_eocd_returns_archive_rejected() -> None:
    assert rejected_code(b"PK\x03\x04" + b"synthetic text, not an archive" * 10) == (
        "archive_rejected"
    )


def test_detect_trailing_data_after_eocd_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(), trailing=b"trailing")

    assert rejected_code(data) == "archive_rejected"


def test_detect_trailing_nul_bytes_after_eocd_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(), trailing=b"\x00" * 16)

    assert rejected_code(data) == "archive_rejected"


def test_detect_eocd_comment_length_past_end_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(), comment=b"abc", comment_length=10)

    assert rejected_code(data) == "archive_rejected"


def test_detect_eocd_further_than_scan_window_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(), trailing=b"a" * 70_000)

    assert rejected_code(data) == "archive_rejected"


def test_detect_eocd_disk_number_not_zero_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), disk_number=1)) == "archive_rejected"


def test_detect_eocd_central_directory_disk_not_zero_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), cd_disk=1)) == "archive_rejected"


def test_detect_eocd_disk_entries_differ_from_total_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), disk_entries=2)) == "archive_rejected"


def test_detect_zip64_locator_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), zip64_locator=True)) == "archive_rejected"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"total_entries": 0xFFFF, "disk_entries": 0xFFFF}, id="entries-ffff"),
        pytest.param({"disk_entries": 0xFFFF}, id="disk-entries-ffff"),
        pytest.param({"cd_size": 0xFFFFFFFF}, id="cd-size-ffffffff"),
        pytest.param({"cd_offset": 0xFFFFFFFF}, id="cd-offset-ffffffff"),
        pytest.param({"disk_number": 0xFFFF, "cd_disk": 0xFFFF}, id="disk-ffff"),
    ],
)
def test_detect_zip64_marker_in_eocd_returns_archive_rejected(overrides: dict[str, int]) -> None:
    assert rejected_code(build_zip(docx_entries(), **overrides)) == "archive_rejected"


# --- Rule 3.2: entry count and central directory bounds --------------------------


def test_detect_entry_count_above_cap_returns_archive_rejected() -> None:
    entries = docx_entries(stored("word/a.xml"), stored("word/b.xml"))  # 5 entries

    assert rejected_code(build_zip(entries), max_entries=4) == "archive_rejected"


def test_detect_entry_count_at_cap_returns_docx() -> None:
    entries = docx_entries(stored("word/a.xml"))  # 4 entries

    assert detect(build_zip(entries), max_entries=4) == kind("DOCX")


def test_detect_entry_count_above_default_cap_returns_archive_rejected() -> None:
    extra = [stored(f"word/media/{i:04d}.txt") for i in range(DEFAULT_MAX_ENTRIES - 2)]
    data = build_zip(docx_entries(*extra))  # 2,001 entries

    assert rejected_code(data) == "archive_rejected"


def test_detect_eocd_claims_more_entries_than_central_directory_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), total_entries=4, disk_entries=4)) == (
        "archive_rejected"
    )


def test_detect_eocd_claims_fewer_entries_than_central_directory_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), total_entries=2, disk_entries=2)) == (
        "archive_rejected"
    )


def test_detect_central_directory_offset_past_end_returns_archive_rejected() -> None:
    data = build_zip(docx_entries())
    data = build_zip(docx_entries(), cd_offset=len(data) + 1000)

    assert rejected_code(data) == "archive_rejected"


def test_detect_central_directory_size_past_eocd_returns_archive_rejected() -> None:
    data = build_zip(docx_entries())
    data = build_zip(docx_entries(), cd_size=len(data))

    assert rejected_code(data) == "archive_rejected"


def test_detect_central_directory_offset_inside_local_header_returns_archive_rejected() -> None:
    assert rejected_code(build_zip(docx_entries(), cd_offset=1)) == "archive_rejected"


# --- Rule 3.3: central directory entries -----------------------------------------


def test_detect_bad_central_directory_signature_returns_archive_rejected() -> None:
    entries = docx_entries()
    entries[1].cd_signature = b"PK\x01\x03"
    assert entries[0].cd_signature == CDH_SIG

    assert rejected_code(build_zip(entries)) == "archive_rejected"


def test_detect_encrypted_main_part_returns_archive_rejected() -> None:
    entries = docx_entries()
    entries[2].flags = FLAG_ENCRYPTED

    assert rejected_code(build_zip(entries)) == "archive_rejected"


def test_detect_encrypted_other_part_returns_archive_rejected() -> None:
    entry = RawEntry(name="docProps/core.xml", data=b"<cp/>", flags=FLAG_ENCRYPTED)

    assert rejected_code(build_zip(docx_entries(entry))) == "archive_rejected"


@pytest.mark.parametrize("method", [1, 6, 9, 12, 14, 93, 95, 98, 99])
def test_detect_unsupported_compression_method_returns_archive_rejected(method: int) -> None:
    entry = RawEntry(name="word/styles.xml", data=b"<styles/>", method=method)

    assert rejected_code(build_zip(docx_entries(entry))) == "archive_rejected"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"a" * 513, id="513-bytes"),
        pytest.param(b"word/doc\x00ument2.xml", id="nul"),
        pytest.param(b"word\\styles.xml", id="backslash"),
        pytest.param(b"/word/styles.xml", id="absolute"),
        pytest.param(b"../evil.xml", id="dotdot-first"),
        pytest.param(b"word/../../evil.xml", id="dotdot-middle"),
        pytest.param(b"word/media/..", id="dotdot-last"),
    ],
)
def test_detect_bad_entry_name_returns_archive_rejected(name: bytes) -> None:
    data = build_zip(docx_entries(stored(name, b"x")))

    assert rejected_code(data) == "archive_rejected"


def test_detect_entry_name_of_512_bytes_returns_docx() -> None:
    name = "word/media/" + "a" * (512 - len("word/media/"))
    assert len(name.encode()) == 512

    assert detect(build_zip(docx_entries(stored(name, b"x")))) == kind("DOCX")


def test_detect_compressed_size_zero_with_uncompressed_above_zero_returns_archive_rejected() -> (
    None
):
    entry = fake_deflated("word/media/a.bin", compressed_size=0, uncompressed_size=1)

    assert rejected_code(build_zip(docx_entries(entry))) == "archive_rejected"


def test_detect_ratio_above_cap_returns_archive_rejected() -> None:
    entry = fake_deflated("word/media/a.bin", compressed_size=1000, uncompressed_size=200_001)

    assert rejected_code(build_zip(docx_entries(entry))) == "archive_rejected"


def test_detect_ratio_at_cap_returns_docx() -> None:
    entry = fake_deflated("word/media/a.bin", compressed_size=1000, uncompressed_size=200_000)

    assert detect(build_zip(docx_entries(entry))) == kind("DOCX")


def test_detect_real_deflate_bomb_entry_returns_archive_rejected() -> None:
    # 4 MiB of zeros deflates to a few KiB: ratio far above 200.
    data = zipfile_archive([*DOCX_PARTS, ("word/media/zeros.bin", b"\x00" * (4 * MIB))])

    assert rejected_code(data) == "archive_rejected"


def test_detect_ratio_respects_configured_cap() -> None:
    entry = fake_deflated("word/media/a.bin", compressed_size=100, uncompressed_size=1100)

    assert rejected_code(build_zip(docx_entries(entry)), max_ratio=10) == "archive_rejected"


def test_detect_declared_total_above_cap_returns_archive_rejected() -> None:
    # 2 x 51 MiB declared = 102 MiB > 100 MiB; each ratio ~170 is below the cap.
    big = 51 * MIB
    entries = docx_entries(
        fake_deflated("word/media/a.bin", compressed_size=300 * 1024, uncompressed_size=big),
        fake_deflated("word/media/b.bin", compressed_size=300 * 1024, uncompressed_size=big),
    )

    assert rejected_code(build_zip(entries)) == "archive_rejected"


def test_detect_declared_total_below_cap_returns_docx() -> None:
    big = 49 * MIB
    entries = docx_entries(
        fake_deflated("word/media/a.bin", compressed_size=300 * 1024, uncompressed_size=big),
        fake_deflated("word/media/b.bin", compressed_size=300 * 1024, uncompressed_size=big),
    )

    assert detect(build_zip(entries)) == kind("DOCX")


def _docx_parts_size() -> int:
    return sum(len(data) for _, data in DOCX_PARTS)


def test_detect_declared_total_exactly_at_configured_cap_returns_docx() -> None:
    cap = _docx_parts_size() + 500

    data = build_zip(docx_entries(stored("word/media/a.bin", b"a" * 500)))

    assert detect(data, max_uncompressed_bytes=cap) == kind("DOCX")


def test_detect_declared_total_one_above_configured_cap_returns_archive_rejected() -> None:
    cap = _docx_parts_size() + 500

    data = build_zip(docx_entries(stored("word/media/a.bin", b"a" * 501)))

    assert rejected_code(data, max_uncompressed_bytes=cap) == "archive_rejected"


# --- Rule 3.4: duplicate names ------------------------------------------------------


def test_detect_exact_duplicate_name_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(stored("word/document.xml", b"<other/>")))

    assert rejected_code(data) == "archive_rejected"


def test_detect_case_folded_duplicate_name_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(stored("WORD/Document.XML", b"<other/>")))

    assert rejected_code(data) == "archive_rejected"


def test_detect_case_folded_duplicate_content_types_returns_archive_rejected() -> None:
    data = build_zip(docx_entries(stored("[content_types].xml", b"<Types/>")))

    assert rejected_code(data) == "archive_rejected"


# --- AC7: error messages carry codes only -------------------------------------------


def _error_for(data: bytes) -> BaseException:
    module = _module()
    with pytest.raises(module.DetectionError) as info:
        module.detect_kind(data, limits=limits())
    return info.value


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda m: b"synthetic\x00" + m.encode(), id="binary"),
        pytest.param(lambda m: b"\x01" * 50 + m.encode(), id="controls"),
        pytest.param(
            lambda m: build_zip(docx_entries(stored(f"word/{m}.xml"), stored(f"WORD/{m}.xml"))),
            id="zip-duplicate-name",
        ),
        pytest.param(
            lambda m: build_zip(docx_entries(stored(f"../{m}.xml"))), id="zip-dotdot-name"
        ),
        pytest.param(lambda m: build_zip(docx_entries(), comment=m.encode()) + b"x", id="eocd"),
        pytest.param(lambda m: b"PK\x03\x04" + m.encode(), id="zip-no-eocd"),
        pytest.param(lambda m: build_zip([stored("Index/Document.iwa", m.encode())]), id="pages"),
        pytest.param(lambda m: OLE2_SAMPLE + m.encode(), id="ole2"),
    ],
)
def test_detection_error_message_contains_no_input(build: Any) -> None:
    marker = new_marker("canary")

    error = _error_for(build(marker))

    assert error.code in DETECTION_CODES  # type: ignore[attr-defined]
    for text in (str(error), repr(error), repr(error.args), repr(vars(error))):
        assert marker not in text


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\x00\x01", id="binary"),
        pytest.param(PNG_SAMPLE, id="png"),
        pytest.param(OLE2_SAMPLE, id="ole2"),
        pytest.param(build_zip([stored("Index/Document.iwa")]), id="pages"),
        pytest.param(build_zip(docx_entries(), trailing=b"x"), id="archive"),
    ],
)
def test_detection_error_code_is_one_of_contract_codes(data: bytes) -> None:
    assert _error_for(data).code in DETECTION_CODES  # type: ignore[attr-defined]
