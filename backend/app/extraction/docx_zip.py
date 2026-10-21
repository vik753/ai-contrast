"""The DOCX archive reader (S3-T2 AC1, AC2; threat model T4, T5).

Runs inside the parsing child (ADR 0011). Every check runs before any part is read;
any failure is ``archive_rejected``.

ZIP layout (APPNOTE.TXT 4.3), on top of the detection rules 3.1 to 3.3 (the same
EOCD, central directory and entry names as detection):

- The local headers lie back to back from offset 0 to the central directory, in
  central-directory order: each entry starts exactly where the previous one ends
  (local header + name + extra + compressed data + optional data descriptor), the
  first at 0, the last ends at ``cd_offset``. So offsets strictly increase, and no
  entry overlaps another or leaves a gap.
- Each local header has the right signature and the same name, flags, method, CRC
  and sizes as its central record. With a data descriptor (flag bit 3) the local
  CRC and sizes are zero or equal, and the descriptor (12 bytes, or 16 with its
  signature; the length is the one that ends where the next entry begins) holds the
  central values.
- Declared sizes: one part at most ``max_part_bytes``, all parts together at most
  ``max_total_bytes``.
- A part is decompressed as a stream; more bytes than declared, fewer bytes, data
  after the end of the deflate stream, or a wrong CRC fail while reading.

OPC part names (ECMA-376 Part 2, 6.2.2): a percent-encoded unreserved character
(``A-Z a-z 0-9 - . _ ~``) or ``/``, a malformed ``%`` sequence or a percent-encoded
sequence that is not UTF-8 → rejected. Names are compared after percent-decoding and
``casefold()``; two entries with the same key → rejected.

Errors carry the code only, never names, offsets or bytes.
"""

from __future__ import annotations

import re
import string
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote

from app.extraction.detect import (
    ARCHIVE_REJECTED,
    DetectionError,
    zip_central_directory,
    zip_entry_name,
)
from app.extraction.model import ExtractionError

# The EOCD entry count is 16 bits; detection applies the real cap before the child.
MAX_ENTRIES: Final = 0xFFFF

LOCAL_SIGNATURE: Final = b"PK\x03\x04"
CENTRAL_SIGNATURE: Final = b"PK\x01\x02"
DESCRIPTOR_SIGNATURE: Final = b"PK\x07\x08"
FLAG_ENCRYPTED: Final = 0x0001
FLAG_DESCRIPTOR: Final = 0x0008
METHOD_STORED: Final = 0
METHOD_DEFLATED: Final = 8
ZIP64_MARKER: Final = 0xFFFFFFFF

# signature, version needed, flags, method, time, date, crc, compressed size,
# uncompressed size, name length, extra length.
_LOCAL: Final = struct.Struct("<4sHHHHHIIIHH")
# signature, version made by, version needed, flags, method, time, date, crc,
# compressed size, uncompressed size, name length, extra length, comment length,
# disk start, internal attributes, external attributes, local header offset.
_CENTRAL: Final = struct.Struct("<4sHHHHHHIIIHHHHHII")
_DESCRIPTOR: Final = struct.Struct("<III")
_SIGNED_DESCRIPTOR_SIZE: Final = len(DESCRIPTOR_SIGNATURE) + _DESCRIPTOR.size

# Compressed bytes fed to zlib at once, and the most bytes one read returns.
IN_CHUNK: Final = 64 * 1024
OUT_CHUNK: Final = 64 * 1024

_UNRESERVED: Final = frozenset(string.ascii_letters + string.digits + "-._~")
_PERCENT: Final = re.compile(r"%(.{0,2})", re.DOTALL)
_HEX2: Final = re.compile(r"[0-9A-Fa-f]{2}")


def reject() -> ExtractionError:
    return ExtractionError(ARCHIVE_REJECTED)


def part_key(name: str) -> str:
    """The comparison key of a part name: percent-decoded (UTF-8) and casefolded.

    Raises ``archive_rejected`` for a malformed or non-UTF-8 percent sequence.
    """
    if "%" in name:
        for match in _PERCENT.finditer(name):
            if _HEX2.fullmatch(match.group(1)) is None:
                raise reject()
        try:
            name = unquote(name, errors="strict")
        except UnicodeDecodeError:
            raise reject() from None
    return name.casefold()


def check_part_name(name: str) -> None:
    """No percent-encoded unreserved character or ``/`` (ECMA-376 Part 2, 6.2.2)."""
    for match in _PERCENT.finditer(name):
        digits = match.group(1)
        if _HEX2.fullmatch(digits) is None:
            raise reject()
        char = chr(int(digits, 16))
        if char in _UNRESERVED or char == "/":
            raise reject()


@dataclass(frozen=True)
class ZipEntry:
    name: str
    method: int
    crc: int
    compressed_size: int
    uncompressed_size: int
    data_start: int


@dataclass(frozen=True)
class _Central:
    raw_name: bytes
    flags: int
    method: int
    crc: int
    compressed_size: int
    uncompressed_size: int
    local_offset: int


def _read_central(data: bytes, start: int, end: int, count: int) -> list[_Central]:
    records: list[_Central] = []
    position = start
    for _ in range(count):
        if position + _CENTRAL.size > end:
            raise reject()
        (
            signature,
            _made_by,
            _needed,
            flags,
            method,
            _time,
            _date,
            crc,
            compressed,
            uncompressed,
            name_length,
            extra_length,
            comment_length,
            _disk,
            _internal,
            _external,
            local_offset,
        ) = _CENTRAL.unpack_from(data, position)
        name_start = position + _CENTRAL.size
        position = name_start + name_length + extra_length + comment_length
        if signature != CENTRAL_SIGNATURE or position > end:
            raise reject()
        if flags & FLAG_ENCRYPTED or method not in (METHOD_STORED, METHOD_DEFLATED):
            raise reject()
        if ZIP64_MARKER in (compressed, uncompressed, local_offset):
            raise reject()
        if method == METHOD_STORED and compressed != uncompressed:
            raise reject()
        records.append(
            _Central(
                raw_name=data[name_start : name_start + name_length],
                flags=flags,
                method=method,
                crc=crc,
                compressed_size=compressed,
                uncompressed_size=uncompressed,
                local_offset=local_offset,
            )
        )
    if position != end:
        raise reject()
    return records


def _check_descriptor(data: bytes, record: _Central, data_end: int, next_start: int) -> None:
    """Check the data descriptor between the data and the next entry."""
    signed = data.startswith(DESCRIPTOR_SIGNATURE, data_end)
    if signed and data_end + _SIGNED_DESCRIPTOR_SIZE == next_start:
        values_at = data_end + len(DESCRIPTOR_SIGNATURE)
    elif data_end + _DESCRIPTOR.size == next_start:
        values_at = data_end
    else:
        raise reject()
    values = _DESCRIPTOR.unpack_from(data, values_at)
    if values != (record.crc, record.compressed_size, record.uncompressed_size):
        raise reject()


def _check_local(data: bytes, record: _Central, next_start: int) -> int:
    """Check one local header against its central record. Return the data start."""
    offset = record.local_offset
    if offset + _LOCAL.size > next_start:
        raise reject()
    (
        signature,
        _needed,
        flags,
        method,
        _time,
        _date,
        crc,
        compressed,
        uncompressed,
        name_length,
        extra_length,
    ) = _LOCAL.unpack_from(data, offset)
    if signature != LOCAL_SIGNATURE or flags != record.flags or method != record.method:
        raise reject()
    name_start = offset + _LOCAL.size
    if data[name_start : name_start + name_length] != record.raw_name:
        raise reject()
    central_values = (record.crc, record.compressed_size, record.uncompressed_size)
    local_values = (crc, compressed, uncompressed)
    data_start: int = name_start + name_length + extra_length
    data_end = data_start + record.compressed_size
    if data_end > next_start:
        raise reject()
    if flags & FLAG_DESCRIPTOR:
        if local_values not in (central_values, (0, 0, 0)):
            raise reject()
        _check_descriptor(data, record, data_end, next_start)
    elif local_values != central_values or data_end != next_start:
        raise reject()
    return data_start


class DocxArchive:
    """A checked archive. Parts are found by ``part_key`` and read as streams."""

    def __init__(self, data: bytes, *, max_part_bytes: int, max_total_bytes: int) -> None:
        self._data = data
        try:
            count, cd_start, cd_end = zip_central_directory(data, max_entries=MAX_ENTRIES)
        except DetectionError:
            raise reject() from None
        records = _read_central(data, cd_start, cd_end, count)
        self._entries: dict[str, ZipEntry] = {}
        expected = 0
        total = 0
        for index, record in enumerate(records):
            # Back to back, in central-directory order, from 0 to the central directory.
            if record.local_offset != expected:
                raise reject()
            following = records[index + 1].local_offset if index + 1 < len(records) else cd_start
            if following <= record.local_offset or following > cd_start:
                raise reject()
            data_start = _check_local(data, record, following)
            expected = following
            total += record.uncompressed_size
            if record.uncompressed_size > max_part_bytes or total > max_total_bytes:
                raise reject()
            self._add(record, data_start)
        if expected != cd_start:
            raise reject()

    def _add(self, record: _Central, data_start: int) -> None:
        is_empty = record.compressed_size == 0 and record.uncompressed_size == 0
        try:
            name = zip_entry_name(record.raw_name, is_empty=is_empty)
        except DetectionError:
            raise reject() from None
        check_part_name(name)
        if name.endswith("/"):
            return  # a directory entry: no part
        key = part_key(name)
        if key in self._entries:
            raise reject()
        self._entries[key] = ZipEntry(
            name=name,
            method=record.method,
            crc=record.crc,
            compressed_size=record.compressed_size,
            uncompressed_size=record.uncompressed_size,
            data_start=data_start,
        )

    def names(self) -> list[str]:
        """The part keys (see ``part_key``)."""
        return list(self._entries)

    def get(self, key: str) -> ZipEntry | None:
        return self._entries.get(key)

    def open(self, entry: ZipEntry) -> PartStream:
        return PartStream(self._chunks(entry))

    def _chunks(self, entry: ZipEntry) -> Iterator[bytes]:
        """The part bytes, checked against the declared size and the CRC."""
        source = memoryview(self._data)[entry.data_start : entry.data_start + entry.compressed_size]
        produced = 0
        crc = 0
        for chunk in _inflate(source) if entry.method == METHOD_DEFLATED else _stored(source):
            produced += len(chunk)
            if produced > entry.uncompressed_size:
                raise reject()
            crc = zlib.crc32(chunk, crc)
            yield chunk
        if produced != entry.uncompressed_size or crc != entry.crc:
            raise reject()


def _stored(source: memoryview) -> Iterator[bytes]:
    for start in range(0, len(source), OUT_CHUNK):
        yield bytes(source[start : start + OUT_CHUNK])


def _inflate(source: memoryview) -> Iterator[bytes]:
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    position = 0
    pending = b""
    try:
        while not inflater.eof:
            if not pending:
                if position >= len(source):
                    break
                pending = bytes(source[position : position + IN_CHUNK])
                position += len(pending)
            chunk = inflater.decompress(pending, OUT_CHUNK)
            pending = inflater.unconsumed_tail
            if chunk:
                yield chunk
    except zlib.error:
        raise reject() from None
    # The deflate stream must end exactly at the end of the compressed data.
    if not inflater.eof or pending or inflater.unused_data or position < len(source):
        raise reject()


class PartStream:
    """A file-like reader over checked part bytes (``read`` only)."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = b""
        self._done = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = OUT_CHUNK
        while not self._buffer and not self._done:
            chunk = next(self._chunks, None)
            if chunk is None:
                self._done = True
            else:
                self._buffer = chunk
        out, self._buffer = self._buffer[:size], self._buffer[size:]
        return out

    def drain(self) -> None:
        """Read to the end, so that the size and CRC checks run."""
        while self.read(OUT_CHUNK):
            pass
