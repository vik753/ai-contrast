"""In-memory ZIP and file fixtures for the stage 2 detection tests (S2-T1).

Everything is built in test code: no binary fixture files and no real
personal data. ``build_zip`` writes a ZIP byte by byte so that a test can
change exactly one field (a flag, a size, a signature, an EOCD value) and
keep the rest of the archive valid. ``test_detect.py`` checks that the
unmodified output is a valid ZIP for the standard library.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

LFH_SIG = b"PK\x03\x04"
CDH_SIG = b"PK\x01\x02"
EOCD_SIG = b"PK\x05\x06"
ZIP64_EOCD_SIG = b"PK\x06\x06"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"

FLAG_ENCRYPTED = 0x0001
FLAG_UTF8 = 0x0800

DOS_TIME = 0
DOS_DATE = (2026 - 1980) << 9 | 1 << 5 | 1

CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" '
    b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    b'<Default Extension="xml" ContentType="application/xml"/>'
    b'<Override PartName="/word/document.xml" ContentType="application/'
    b'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    b"</Types>"
)
RELS_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    b'relationships/officeDocument" Target="word/document.xml"/>'
    b"</Relationships>"
)
DOCUMENT_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>Synthetic test contract. Clause 1. Payment within 30 days."
    b"</w:t></w:r></w:p></w:body></w:document>"
)

DOCX_PARTS: tuple[tuple[str, bytes], ...] = (
    ("[Content_Types].xml", CONTENT_TYPES_XML),
    ("_rels/.rels", RELS_XML),
    ("word/document.xml", DOCUMENT_XML),
)


@dataclass
class RawEntry:
    """One archive member. ``data`` is written as is (already "compressed").

    Sizes and CRC default to values that match ``data`` for a stored entry.
    """

    name: bytes | str
    data: bytes = b""
    method: int = 0
    flags: int = 0
    compressed_size: int | None = None
    uncompressed_size: int | None = None
    crc: int | None = None
    cd_signature: bytes = CDH_SIG
    extra: bytes = field(default=b"")

    def name_bytes(self) -> bytes:
        if isinstance(self.name, bytes):
            return self.name
        return self.name.encode("utf-8")

    def all_flags(self) -> int:
        flags = self.flags
        if isinstance(self.name, str) and not self.name.isascii():
            flags |= FLAG_UTF8
        return flags

    def sizes(self) -> tuple[int, int]:
        csize = len(self.data) if self.compressed_size is None else self.compressed_size
        usize = len(self.data) if self.uncompressed_size is None else self.uncompressed_size
        return csize, usize

    def crc_value(self) -> int:
        return zlib.crc32(self.data) if self.crc is None else self.crc


def stored(name: bytes | str, data: bytes = b"") -> RawEntry:
    return RawEntry(name=name, data=data)


def fake_deflated(
    name: str, *, compressed_size: int, uncompressed_size: int, fill: int = 0x5A
) -> RawEntry:
    """A method-8 entry with ``compressed_size`` real (garbage) bytes and a
    declared uncompressed size. Nothing in stage 2 decompresses it."""
    return RawEntry(
        name=name,
        data=bytes([fill]) * compressed_size,
        method=8,
        compressed_size=compressed_size,
        uncompressed_size=uncompressed_size,
        crc=0x12345678,
    )


def docx_entries(*extra: RawEntry) -> list[RawEntry]:
    """The three parts of a minimal DOCX (stored) plus ``extra`` entries."""
    return [stored(name, data) for name, data in DOCX_PARTS] + list(extra)


def build_zip(  # noqa: PLR0913 - every keyword is one field a test may break
    entries: list[RawEntry],
    *,
    comment: bytes = b"",
    trailing: bytes = b"",
    disk_number: int = 0,
    cd_disk: int | None = None,
    disk_entries: int | None = None,
    total_entries: int | None = None,
    cd_size: int | None = None,
    cd_offset: int | None = None,
    comment_length: int | None = None,
    zip64_locator: bool = False,
    between_cd_and_eocd: bytes = b"",
) -> bytes:
    """Write a ZIP archive. Every ``None`` keyword gets the correct value."""
    out = io.BytesIO()
    offsets: list[int] = []
    for entry in entries:
        offsets.append(out.tell())
        name = entry.name_bytes()
        csize, usize = entry.sizes()
        out.write(LFH_SIG)
        out.write(
            struct.pack(
                "<HHHHHIIIHH",
                20,
                entry.all_flags(),
                entry.method,
                DOS_TIME,
                DOS_DATE,
                entry.crc_value(),
                csize & 0xFFFFFFFF,
                usize & 0xFFFFFFFF,
                len(name),
                len(entry.extra),
            )
        )
        out.write(name)
        out.write(entry.extra)
        out.write(entry.data)

    real_cd_offset = out.tell()
    for entry, local_offset in zip(entries, offsets, strict=True):
        name = entry.name_bytes()
        csize, usize = entry.sizes()
        out.write(entry.cd_signature)
        out.write(
            struct.pack(
                "<HHHHHHIIIHHHHHII",
                20,
                20,
                entry.all_flags(),
                entry.method,
                DOS_TIME,
                DOS_DATE,
                entry.crc_value(),
                csize & 0xFFFFFFFF,
                usize & 0xFFFFFFFF,
                len(name),
                len(entry.extra),
                0,
                0,
                0,
                0,
                local_offset,
            )
        )
        out.write(name)
        out.write(entry.extra)
    real_cd_size = out.tell() - real_cd_offset

    if zip64_locator:
        zip64_eocd_offset = out.tell()
        out.write(ZIP64_EOCD_SIG)
        out.write(
            struct.pack(
                "<QHHIIQQQQ",
                44,
                45,
                45,
                0,
                0,
                len(entries),
                len(entries),
                real_cd_size,
                real_cd_offset,
            )
        )
        out.write(ZIP64_LOCATOR_SIG)
        out.write(struct.pack("<IQI", 0, zip64_eocd_offset, 1))
    out.write(between_cd_and_eocd)

    count = len(entries)
    out.write(EOCD_SIG)
    out.write(
        struct.pack(
            "<HHHHIIH",
            disk_number,
            disk_number if cd_disk is None else cd_disk,
            count if disk_entries is None else disk_entries,
            count if total_entries is None else total_entries,
            real_cd_size if cd_size is None else cd_size,
            real_cd_offset if cd_offset is None else cd_offset,
            len(comment) if comment_length is None else comment_length,
        )
    )
    out.write(comment)
    out.write(trailing)
    return out.getvalue()


def local_section(entries: list[RawEntry], *, base: int = 0) -> tuple[bytes, list[int]]:
    """Local headers and data of ``entries`` as written by ``build_zip``,
    placed at file offset ``base``. Returns the bytes and each header offset."""
    data = build_zip(entries)
    cd_start = len(data) - 22 - _central_size(entries)
    first = [0]
    for entry in entries[:-1]:
        first.append(first[-1] + 30 + len(entry.name_bytes()) + len(entry.extra) + len(entry.data))
    return data[:cd_start], [base + offset for offset in first]


def _central_size(entries: list[RawEntry]) -> int:
    return sum(46 + len(e.name_bytes()) + len(e.extra) for e in entries)


def central_section(entries: list[RawEntry], offsets: list[int]) -> bytes:
    """Central directory records of ``entries`` pointing at ``offsets``."""
    out = io.BytesIO()
    for entry, local_offset in zip(entries, offsets, strict=True):
        name = entry.name_bytes()
        csize, usize = entry.sizes()
        out.write(entry.cd_signature)
        out.write(
            struct.pack(
                "<HHHHHHIIIHHHHHII",
                20,
                20,
                entry.all_flags(),
                entry.method,
                DOS_TIME,
                DOS_DATE,
                entry.crc_value(),
                csize & 0xFFFFFFFF,
                usize & 0xFFFFFFFF,
                len(name),
                len(entry.extra),
                0,
                0,
                0,
                0,
                local_offset,
            )
        )
        out.write(name)
        out.write(entry.extra)
    return out.getvalue()


def eocd_record(*, count: int, cd_size: int, cd_offset: int, comment: bytes = b"") -> bytes:
    """A one-disk EOCD record with ``comment``."""
    return (
        EOCD_SIG
        + struct.pack("<HHHHIIH", 0, 0, count, count, cd_size, cd_offset, len(comment))
        + comment
    )


def second_central_directory_archive() -> tuple[bytes, list[str], list[str]]:
    """``[locals benign][locals evil][CD benign][CD evil][EOCD -> CD benign]``.

    The EOCD ``cd_offset`` points at the benign directory, but the evil
    directory has the same size and ends at the EOCD. Python ``zipfile``
    locates the directory as ``eocd_offset - cd_size`` and reads the evil one.
    Returns the archive, the benign names and the evil names.
    """
    benign = docx_entries()
    evil = [stored(name, data) for name, data in _evil_parts()]
    local_bytes, offsets = local_section(benign + evil)
    cd_benign = central_section(benign, offsets[: len(benign)])
    cd_evil = central_section(evil, offsets[len(benign) :])
    assert len(cd_benign) == len(cd_evil)
    cd_offset = len(local_bytes)
    data = (
        local_bytes
        + cd_benign
        + cd_evil
        + eocd_record(count=len(benign), cd_size=len(cd_benign), cd_offset=cd_offset)
    )
    return data, [e.name_bytes().decode() for e in benign], [e.name_bytes().decode() for e in evil]


def fake_eocd_in_comment_archive(*, fake_comment: bytes = b"") -> tuple[bytes, list[str]]:
    """A valid DOCX whose EOCD comment holds a second central directory and a
    fake EOCD that points at it (with ``fake_comment`` after it, so the fake
    comment also ends at the end of the file). Returns the archive and the
    names in the hidden directory."""
    benign = docx_entries()
    evil = [stored(name, data) for name, data in _evil_parts()]
    local_bytes, offsets = local_section(benign + evil)
    cd_benign = central_section(benign, offsets[: len(benign)])
    cd_evil = central_section(evil, offsets[len(benign) :])
    real_eocd_offset = len(local_bytes) + len(cd_benign)
    evil_cd_offset = real_eocd_offset + 22  # the comment starts after the fixed record
    fake = eocd_record(
        count=len(evil), cd_size=len(cd_evil), cd_offset=evil_cd_offset, comment=fake_comment
    )
    real = eocd_record(
        count=len(benign),
        cd_size=len(cd_benign),
        cd_offset=len(local_bytes),
        comment=cd_evil + fake,
    )
    return local_bytes + cd_benign + real, [e.name_bytes().decode() for e in evil]


def _evil_parts() -> tuple[tuple[str, bytes], ...]:
    """Same name lengths as ``DOCX_PARTS``, so both directories have the same size."""
    return (
        ("[Content_Types].xml", CONTENT_TYPES_XML),
        ("_rels/.rels", RELS_XML),
        ("word/documenX.xml", b"<w:document>Hidden clause (synthetic).</w:document>"),
    )


def zipfile_archive(
    members: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    comment: bytes = b"",
) -> bytes:
    """An archive written by the standard library ``zipfile`` module."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in members:
            archive.writestr(name, data)
        if comment:
            archive.comment = comment
    return buffer.getvalue()


def minimal_docx() -> bytes:
    """A small valid DOCX package, deflated, written by ``zipfile``."""
    return zipfile_archive(list(DOCX_PARTS))


# --- Non-ZIP samples (synthetic) --------------------------------------------

PDF_SAMPLE = (
    b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n"
    b"%%EOF\n"
)
OLE2_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
OLE2_SAMPLE = OLE2_SIGNATURE + b"\x00" * 504 + b"synthetic"

# The remainder of each image/RTF sample is plain ASCII text. Without the
# signature rule these samples would be classified as text, so the tests
# show that the signature itself is checked.
TEXT_TAIL = b" synthetic sample text for the detection tests." * 40
PNG_SAMPLE = b"\x89PNG\r\n\x1a\n" + TEXT_TAIL
JPEG_SAMPLE = b"\xff\xd8\xff\xe0" + TEXT_TAIL
GIF87_SAMPLE = b"GIF87a" + TEXT_TAIL
GIF89_SAMPLE = b"GIF89a" + TEXT_TAIL
TIFF_LE_SAMPLE = b"II*\x00" + TEXT_TAIL
TIFF_BE_SAMPLE = b"MM\x00*" + TEXT_TAIL
WEBP_SAMPLE = b"RIFFabcdWEBP" + TEXT_TAIL
RTF_SAMPLE = b"{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Arial;}} Synthetic test contract.\\par }"

ENGLISH_TEXT = (
    "SERVICE AGREEMENT (synthetic test data)\n\n"
    "1. The Provider delivers the services described in Annex 1.\r\n"
    "2. The Client pays within 30 days.\f\n"
    "\tSigned: Party A, Party B.\n"
)
UKRAINIAN_TEXT = "Договір надання послуг (тестові дані). Оплата протягом 30 днів.\n"
RUSSIAN_TEXT = "Договор оказания услуг (тестовые данные). Оплата в течение 30 дней.\n"
