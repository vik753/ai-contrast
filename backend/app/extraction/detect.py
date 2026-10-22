"""File type detection by magic bytes and ZIP structure (threat model T4, ADR 0010).

``detect_kind`` is a pure function on bytes in memory. It never decompresses,
never parses XML and never trusts a file name or a declared media type. Its work
is bounded: fixed-size signatures, the first 64 KiB for text, the last 65,557
bytes to find the ZIP end-of-central-directory record, and a central directory
whose entry count is checked against the cap before any per-entry work.

Rules (docs/agent/TASKS.md, Stage 2, "Detection rules"):

1. ``%PDF-`` at offset 0 is a PDF.
2. An OLE2 container (old ``.doc``, password-protected Office file) is rejected
   with ``legacy_office_unsupported``.
3. ``PK\\x03\\x04`` at offset 0 goes through the ZIP checks. A structure failure is
   ``archive_rejected``; the archive is then classified by entry names only.
4. Image and RTF signatures are ``unsupported_type``.
5. A UTF-16 BOM with an even total length is text (odd length: ``unsupported_type``).
   Anything else is plain text (a UTF-8 BOM is skipped first), unless the first
   64 KiB hold a NUL byte or more than 1 % C0 control characters other than TAB,
   LF, CR and FF. This only classifies; stage 3 decodes strictly and fails closed.

The ZIP checks read an archive the same way as Python ``zipfile`` (the stage 3
reader): the same EOCD record, a central directory that ends exactly at it, and the
same entry count, so both see the same entry names.

``DetectionError`` carries a fixed code only. Its message never holds input bytes,
entry names or offsets, so it is safe to log and to return.
"""

from __future__ import annotations

import re
import string
import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"


class DetectionError(Exception):
    """The file is rejected. ``code`` is one of the ``422`` codes of the API contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int
    max_uncompressed_bytes: int
    max_ratio: int


EMPTY_FILE: Final = "empty_file"
UNSUPPORTED_TYPE: Final = "unsupported_type"
LEGACY_OFFICE_UNSUPPORTED: Final = "legacy_office_unsupported"
PAGES_UNSUPPORTED: Final = "pages_unsupported"
ARCHIVE_REJECTED: Final = "archive_rejected"

# --- Signatures -------------------------------------------------------------------

PDF_SIGNATURE: Final = b"%PDF-"
OLE2_SIGNATURE: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_LOCAL_HEADER_SIGNATURE: Final = b"PK\x03\x04"
REJECTED_SIGNATURES: Final = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
    b"II*\x00",  # TIFF, little endian
    b"MM\x00*",  # TIFF, big endian
    b"RIFF",  # RIFF container (WebP and others)
    b"{\\rtf",  # RTF
)
UTF8_BOM: Final = b"\xef\xbb\xbf"
UTF16_BOMS: Final = (
    b"\xff\xfe",  # UTF-16 LE
    b"\xfe\xff",  # UTF-16 BE
)

# --- Plain text heuristics ----------------------------------------------------------

TEXT_SAMPLE_BYTES: Final = 64 * 1024
MAX_CONTROL_PERCENT: Final = 1
# C0 controls except NUL (checked on its own), TAB, LF, FF and CR.
_CONTROL_BYTES: Final = bytes(b for b in range(0x20) if b not in {0x00, 0x09, 0x0A, 0x0C, 0x0D})
# Deleting every other byte value leaves only the counted controls; `translate` runs
# in C, so the count is one pass over at most 64 KiB without a Python loop.
_NOT_CONTROL_BYTES: Final = bytes(b for b in range(256) if b not in _CONTROL_BYTES)

# --- ZIP structure (APPNOTE.TXT 6.3) ---------------------------------------------------

EOCD_SIGNATURE: Final = b"PK\x05\x06"
CENTRAL_HEADER_SIGNATURE: Final = b"PK\x01\x02"
ZIP64_EOCD_SIGNATURE: Final = b"PK\x06\x06"
ZIP64_LOCATOR_SIGNATURE: Final = b"PK\x06\x07"
# None of these may appear in the archive comment: another reader could take one
# of them as the end of the archive.
COMMENT_FORBIDDEN_SIGNATURES: Final = (
    EOCD_SIGNATURE,
    ZIP64_EOCD_SIGNATURE,
    ZIP64_LOCATOR_SIGNATURE,
)

# signature, disk, cd disk, entries on disk, total entries, cd size, cd offset,
# comment length.
_EOCD: Final = struct.Struct("<4sHHHHIIH")
# signature, version made by, version needed, flags, method, time, date, crc,
# compressed size, uncompressed size, name length, extra length, comment length,
# disk start, internal attributes, external attributes, local header offset.
_CENTRAL_HEADER: Final = struct.Struct("<4sHHHHHHIIIHHHHHII")
ZIP64_LOCATOR_SIZE: Final = 20
MAX_COMMENT_LENGTH: Final = 0xFFFF
EOCD_SCAN_BYTES: Final = _EOCD.size + MAX_COMMENT_LENGTH  # 65,557

ZIP64_MARKER_16: Final = 0xFFFF
ZIP64_MARKER_32: Final = 0xFFFFFFFF
FLAG_ENCRYPTED: Final = 0x0001
METHOD_STORED: Final = 0
METHOD_DEFLATED: Final = 8
MAX_NAME_BYTES: Final = 512

DOCX_REQUIRED_NAMES: Final = frozenset({"[content_types].xml", "_rels/.rels"})
NON_WORD_OOXML_PREFIXES: Final = ("xl/", "ppt/")
PAGES_INDEX_PREFIX: Final = "index/"
PAGES_INDEX_SUFFIX: Final = ".iwa"
_ASCII_LETTERS: Final = frozenset(string.ascii_letters)
# Entry names: printable ASCII only (OPC part names are ASCII), 1 to 512 bytes.
_PRINTABLE_ASCII_NAME: Final = re.compile(rb"[\x20-\x7e]{1,%d}" % MAX_NAME_BYTES)


def detect_kind(data: bytes, *, limits: ZipLimits) -> FileKind:
    """Return the kind of ``data`` or raise ``DetectionError`` with a contract code."""
    if not data:
        raise DetectionError(EMPTY_FILE)
    if data.startswith(PDF_SIGNATURE):
        return FileKind.PDF
    if data.startswith(OLE2_SIGNATURE):
        raise DetectionError(LEGACY_OFFICE_UNSUPPORTED)
    if data.startswith(ZIP_LOCAL_HEADER_SIGNATURE):
        return _classify_zip(_zip_entry_names(data, limits))
    if data.startswith(REJECTED_SIGNATURES):
        raise DetectionError(UNSUPPORTED_TYPE)
    return _check_plain_text(data)


def _check_plain_text(data: bytes) -> FileKind:
    if data.startswith(UTF16_BOMS):
        # UTF-16 text is made of 2-byte code units.
        if len(data) % 2:
            raise DetectionError(UNSUPPORTED_TYPE)
        return FileKind.TEXT
    start = len(UTF8_BOM) if data.startswith(UTF8_BOM) else 0
    sample = data[start : start + TEXT_SAMPLE_BYTES]
    if b"\x00" in sample:
        raise DetectionError(UNSUPPORTED_TYPE)
    controls = len(sample.translate(None, _NOT_CONTROL_BYTES))
    if controls * 100 > len(sample) * MAX_CONTROL_PERCENT:
        raise DetectionError(UNSUPPORTED_TYPE)
    return FileKind.TEXT


def _reject() -> DetectionError:
    return DetectionError(ARCHIVE_REJECTED)


def _ends_at_eof(data: bytes, offset: int) -> bool:
    """True if an EOCD record at ``offset`` is complete and its comment ends exactly
    at the end of ``data``."""
    record_end = offset + _EOCD.size
    if record_end > len(data):
        return False
    comment_length: int = struct.unpack_from("<H", data, record_end - 2)[0]
    return record_end + comment_length == len(data)


def _find_eocd(data: bytes) -> int:
    """Offset of the EOCD record, chosen the same way as Python ``zipfile``.

    ``zipfile`` takes the last EOCD signature in the last 65,557 bytes. This returns
    that offset only if, in addition:

    - the record is complete and its comment ends exactly at the end of the file;
    - the comment holds no EOCD, ZIP64 EOCD or ZIP64 locator signature;
    - no earlier EOCD signature in the window also has a comment that ends exactly
      at the end of the file (a second, nested EOCD that another reader could use).

    So exactly one record can be read as the end of the archive. Otherwise the
    archive is rejected.
    """
    window_start = max(0, len(data) - EOCD_SCAN_BYTES)
    offset = data.rfind(EOCD_SIGNATURE, window_start)
    if offset < 0 or not _ends_at_eof(data, offset):
        raise _reject()
    comment = data[offset + _EOCD.size :]
    if any(signature in comment for signature in COMMENT_FORBIDDEN_SIGNATURES):
        raise _reject()
    other = data.rfind(EOCD_SIGNATURE, window_start, offset + len(EOCD_SIGNATURE) - 1)
    while other >= 0:
        if _ends_at_eof(data, other):
            raise _reject()
        other = data.rfind(EOCD_SIGNATURE, window_start, other + len(EOCD_SIGNATURE) - 1)
    return offset


def _central_directory(data: bytes, limits: ZipLimits) -> tuple[int, int, int]:
    """Rules 3.1 and 3.2. Return the entry count and the central directory bounds."""
    # 3.1: EOCD, one disk, no ZIP64.
    eocd = _find_eocd(data)
    (
        _signature,
        disk,
        cd_disk,
        disk_entries,
        total_entries,
        cd_size,
        cd_offset,
        _comment_length,
    ) = _EOCD.unpack_from(data, eocd)
    if disk != 0 or cd_disk != 0 or disk_entries != total_entries:
        raise _reject()
    if ZIP64_MARKER_16 in (disk_entries, total_entries) or ZIP64_MARKER_32 in (cd_size, cd_offset):
        raise _reject()
    locator = eocd - ZIP64_LOCATOR_SIZE
    if locator >= 0 and data.startswith(ZIP64_LOCATOR_SIGNATURE, locator):
        raise _reject()

    # 3.2: entry count before any per-entry work. The central directory ends exactly
    # at the EOCD: `zipfile` locates it as `eocd - cd_size` and ignores `cd_offset`,
    # so a gap would let it read a different directory than this one.
    if total_entries > limits.max_entries:
        raise _reject()
    cd_end = cd_offset + cd_size
    if cd_end != eocd:
        raise _reject()
    return total_entries, cd_offset, cd_end


def _read_entry(
    view: memoryview, position: int, cd_end: int, limits: ZipLimits
) -> tuple[str, int, int]:
    """Rule 3.3 for one central directory entry at ``position``.

    Return the decoded name, the declared uncompressed size and the next position.
    """
    if position + _CENTRAL_HEADER.size > cd_end:
        raise _reject()
    (
        signature,
        _made_by,
        _needed,
        flags,
        method,
        _time,
        _date,
        _crc,
        compressed,
        uncompressed,
        name_length,
        extra_length,
        comment_length,
        _disk_start,
        _internal,
        _external,
        _local_offset,
    ) = _CENTRAL_HEADER.unpack_from(view, position)
    if signature != CENTRAL_HEADER_SIGNATURE:
        raise _reject()
    if flags & FLAG_ENCRYPTED or method not in (METHOD_STORED, METHOD_DEFLATED):
        raise _reject()
    if ZIP64_MARKER_32 in (compressed, uncompressed):
        raise _reject()
    name_start = position + _CENTRAL_HEADER.size
    next_position = name_start + name_length + extra_length + comment_length
    if next_position > cd_end:
        raise _reject()
    # Compressed size 0 only for an empty entry; then the ratio is checked.
    if compressed == 0 and uncompressed != 0:
        raise _reject()
    if uncompressed > compressed * limits.max_ratio:
        raise _reject()
    name = _entry_name(bytes(view[name_start : name_start + name_length]))
    _check_name(name, is_empty=uncompressed == 0 and compressed == 0)
    return name, uncompressed, next_position


def _zip_entry_names(data: bytes, limits: ZipLimits) -> list[str]:
    """Run the ZIP structure checks (rules 3.1 to 3.4). Return the decoded names."""
    total_entries, position, cd_end = _central_directory(data, limits)
    view = memoryview(data)
    names: list[str] = []
    folded: set[str] = set()
    declared_total = 0
    for _ in range(total_entries):
        name, uncompressed, position = _read_entry(view, position, cd_end, limits)
        declared_total += uncompressed
        if declared_total > limits.max_uncompressed_bytes:
            raise _reject()
        # 3.4: OPC part names are case-insensitive.
        key = name.casefold()
        if key in folded:
            raise _reject()
        folded.add(key)
        names.append(name)
    # The EOCD entry count must match the entries actually present.
    if position != cd_end:
        raise _reject()
    return names


def _entry_name(raw: bytes) -> str:
    """The name as text: 1 to 512 bytes of printable ASCII (0x20-0x7E), else rejected.

    The UTF-8 flag (bit 11) does not matter: an ASCII name reads the same in UTF-8
    and CP437, so every reader sees the same name.
    """
    if _PRINTABLE_ASCII_NAME.fullmatch(raw) is None:
        raise _reject()
    return raw.decode("ascii")


def _check_name(name: str, *, is_empty: bool) -> None:
    """Rule 3.3 name shape. ``word/%64ocument.xml`` passes: OPC part-name grammar
    and percent-decoding are stage 3 rules."""
    if "\\" in name:
        raise _reject()
    # Absolute: a leading "/" or a drive letter ("C:").
    if name.startswith("/") or (name[:1] in _ASCII_LETTERS and name[1:2] == ":"):
        raise _reject()
    path = name
    if name.endswith("/"):
        # A trailing "/" marks a directory entry, which must hold no data.
        if not is_empty:
            raise _reject()
        path = name[:-1]
    for segment in path.split("/"):
        # No empty, "." or ".." segment and no segment ending in "." (Windows drops it).
        if not segment or segment.endswith("."):
            raise _reject()


def _classify_zip(names: list[str]) -> FileKind:
    """Rule 3.5: classification by entry names only (case-insensitive, like OPC)."""
    folded = [name.casefold() for name in names]
    if any(n.startswith(PAGES_INDEX_PREFIX) and n.endswith(PAGES_INDEX_SUFFIX) for n in folded):
        raise DetectionError(PAGES_UNSUPPORTED)
    if set(folded) >= DOCX_REQUIRED_NAMES and not any(
        n.startswith(NON_WORD_OOXML_PREFIXES) for n in folded
    ):
        return FileKind.DOCX
    raise DetectionError(UNSUPPORTED_TYPE)


# --- Shared with the DOCX reader (S3-T2) -----------------------------------------------


def zip_central_directory(data: bytes, *, max_entries: int) -> tuple[int, int, int]:
    """Rules 3.1 and 3.2 for the stage 3 ZIP reader: the same EOCD and central
    directory as detection. Return the entry count and the central directory bounds
    (start, end). Raises ``DetectionError(archive_rejected)``."""
    limits = ZipLimits(max_entries=max_entries, max_uncompressed_bytes=0, max_ratio=0)
    return _central_directory(data, limits)


def zip_entry_name(raw: bytes, *, is_empty: bool) -> str:
    """Rule 3.3 for one entry name, as in detection. Raises
    ``DetectionError(archive_rejected)``."""
    name = _entry_name(raw)
    _check_name(name, is_empty=is_empty)
    return name
